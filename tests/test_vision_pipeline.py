import unittest
from app.config import SpatialZones
from app.vision import (
    Detection,
    ByteTrack,
    SpatialClassifier,
    InfrastructureStateEstimator,
)
from app.vision.tracker import compute_iou

class TestVisionPipeline(unittest.TestCase):
    def test_compute_iou(self):
        b1 = [0, 0, 10, 10]
        b2 = [5, 0, 15, 10]
        iou = compute_iou(b1, b2)
        # Intersection is 5x10 = 50, union is 100 + 100 - 50 = 150 -> 1/3
        self.assertAlmostEqual(iou, 1.0 / 3.0, places=3)

    def test_bytetrack_association(self):
        tracker = ByteTrack(high_thresh=0.5, low_thresh=0.1)
        det1 = Detection("vehicle", 0.9, (100, 100, 150, 150), 125, 125, 50, 50, 2500)
        tracks = tracker.update([det1], ts=1000.0)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, 1)

        # Move slightly next frame (high overlap)
        det2 = Detection("vehicle", 0.85, (105, 100, 155, 150), 130, 125, 50, 50, 2500)
        tracks2 = tracker.update([det2], ts=1000.1)
        self.assertEqual(len(tracks2), 1)
        self.assertEqual(tracks2[0].track_id, 1)
        self.assertEqual(len(tracks2[0].history), 2)

    def test_spatial_classifier_roadway(self):
        zones = SpatialZones(roadway_midline_x=0.5)
        classifier = SpatialClassifier(zones=zones, frame_width=1000, frame_height=500)

        # Vehicle moving left to right across midline (500px) over multiple 10 FPS frames
        tracker = ByteTrack(match_thresh=0.2)
        # Box width is 120px. Moving 15px each frame guarantees high IoU overlap
        x = 420
        tracks = []
        for i in range(5):
            det = Detection("vehicle", 0.9, (x, 230, x + 120, 270), x + 60, 250, 120, 40, 4800)
            tracks = tracker.update([det], ts=1.0 + i * 0.1)
            x += 15

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, 1)
        self.assertEqual(len(tracks[0].history), 5)

        crossings, passages = classifier.evaluate_tracks(tracks, ts=1.5)
        self.assertEqual(len(crossings), 1)
        self.assertEqual(crossings[0].kind, "vehicle")
        self.assertEqual(crossings[0].direction, "southbound")

    def test_spatial_classifier_marine_channel(self):
        zones = SpatialZones()
        classifier = SpatialClassifier(zones=zones, frame_width=1000, frame_height=500)

        # Boat in channel moving up and right (Round Lake inbound) at steady no-wake speed
        tracker = ByteTrack(match_thresh=0.2)
        bx, by = 280, 410
        tracks = []
        for i in range(6):
            det = Detection("vessel", 0.9, (bx, by, bx + 100, by + 60), bx + 50, by + 30, 100, 60, 6000)
            tracks = tracker.update([det], ts=1.0 + i * 0.2)
            bx += 6
            by -= 4  # moving up-right

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, 1)

        crossings, passages = classifier.evaluate_tracks(tracks, ts=2.2)
        self.assertEqual(len(passages), 1)
        self.assertEqual(passages[0].kind, "vessel")
        self.assertEqual(passages[0].direction, "inbound")

    def test_seawall_rejection(self):
        zones = SpatialZones()
        classifier = SpatialClassifier(zones=zones, frame_width=1000, frame_height=1000)
        # South boardwalk coordinate: cx > 0.43 and cy > 0.74
        self.assertTrue(classifier.is_seawall_or_pier(0.50, 0.80))
        self.assertFalse(classifier.in_channel(0.50, 0.80))

    def test_infrastructure_state_estimator(self):
        zones = SpatialZones()
        estimator = InfrastructureStateEstimator(zones=zones)

        # Down state
        state1 = estimator.estimate([])
        self.assertEqual(state1.leaf_state, "down")
        self.assertEqual(state1.gate_state, "raised")

        # Leaf lifting with gate reported raised -> invariant forces gate lowered!
        det_leaf = Detection("leaf_span", 0.8, (0, 0, 50, 50), 25, 25, 50, 50, 2500)
        state2 = estimator.estimate([det_leaf], raw_leaf_angle=45.0, raw_gate_state="raised")
        self.assertEqual(state2.leaf_state, "up")
        self.assertEqual(state2.gate_state, "lowered")
        self.assertGreater(state2.percent_open, 50)

if __name__ == "__main__":
    unittest.main()
