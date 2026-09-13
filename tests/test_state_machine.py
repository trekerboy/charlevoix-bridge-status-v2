import unittest
from app.state_machine import BridgeStateMachine

class TestStateMachine(unittest.TestCase):
    def test_milestone_transitions(self):
        milestones = []
        completed = []

        sm = BridgeStateMachine(
            debounce_count=2,
            on_milestone=lambda kind, ts, meta: milestones.append((kind, ts)),
            on_cycle_complete=lambda cycle: completed.append(cycle),
        )

        t = 1000.0
        # 1. Gates lower (2 consecutive frames)
        sm.update(t, leaf_state="down", gate_state="lowered", percent_open=0)
        self.assertEqual(len(milestones), 0)
        t += 1.0
        sm.update(t, leaf_state="down", gate_state="lowered", percent_open=0)
        self.assertIn("road_blocked", [m[0] for m in milestones])

        # 2. Leaves lift
        t += 5.0
        sm.update(t, leaf_state="moving", gate_state="lowered", percent_open=15)
        t += 1.0
        sm.update(t, leaf_state="moving", gate_state="lowered", percent_open=25)
        self.assertIn("lift_start", [m[0] for m in milestones])

        # 3. Peak openness
        t += 10.0
        sm.update(t, leaf_state="up", gate_state="lowered", percent_open=90)
        self.assertIn("full_open", [m[0] for m in milestones])

        # 4. Seated
        t += 20.0
        sm.update(t, leaf_state="down", gate_state="lowered", percent_open=0)
        t += 1.0
        sm.update(t, leaf_state="down", gate_state="lowered", percent_open=0)
        self.assertIn("seated", [m[0] for m in milestones])

        # 5. Gates clear -> triggers cycle completion
        t += 5.0
        sm.update(t, leaf_state="down", gate_state="raised", percent_open=0)
        t += 1.0
        sm.update(t, leaf_state="down", gate_state="raised", percent_open=0)
        self.assertIn("road_clear", [m[0] for m in milestones])

        self.assertEqual(len(completed), 1)
        cycle = completed[0]
        self.assertGreater(cycle.pre_opening_wait_s, 0)
        self.assertGreater(cycle.road_closure_s, 0)
        self.assertGreater(cycle.lift_duration_s, 0)

if __name__ == "__main__":
    unittest.main()
