/* Visual Event Auditor & Ground Truth Certification */
(function() {
  let captures = [];
  let currentCaptureId = null;
  let frames = [];
  let currentFrameIdx = 0;
  let isPlaying = false;
  let playInterval = null;
  let currentRecognition = null;

  const auditRecord = {
    schema_version: '2.0',
    event_id: '',
    milestones: {
      road_blocked: null,
      lift_start: null,
      full_open: null,
      lower_start: null,
      seated: null,
      road_clear: null,
      traffic_resumed: null,
    },
    peak_openness_percent: 100,
    boats: { inbound: 0, outbound: 0 },
    conditions: { environment: 'daylight' },
    reviewer_notes: '',
  };

  const captureSelect = document.getElementById('captureSelect');
  const canvas = document.getElementById('auditCanvas');
  const ctx = canvas.getContext('2d');
  const frameSlider = document.getElementById('frameSlider');
  const frameCounter = document.getElementById('frameCounter');
  const frameTs = document.getElementById('frameTs');
  const playBtn = document.getElementById('playBtn');
  const prevFrameBtn = document.getElementById('prevFrameBtn');
  const nextFrameBtn = document.getElementById('nextFrameBtn');
  const recognizeBtn = document.getElementById('recognizeBtn');
  const saveAuditBtn = document.getElementById('saveAuditBtn');
  const exportGoldenBtn = document.getElementById('exportGoldenBtn');
  const saveStatus = document.getElementById('saveStatus');
  const hudCard = document.getElementById('hudCard');
  const hudLatency = document.getElementById('hudLatency');
  const hudBody = document.getElementById('hudBody');
  const boatsInInput = document.getElementById('boatsInInput');
  const boatsOutInput = document.getElementById('boatsOutInput');
  const notesInput = document.getElementById('notesInput');

  // Load capture events
  async function loadCaptures() {
    try {
      const res = await fetch('/api/captures');
      if (!res.ok) throw new Error('Captures unavailable');
      captures = await res.json();
      captureSelect.innerHTML = '';

      if (captures.length === 0) {
        captureSelect.innerHTML = '<option value="">No recorded openings found</option>';
        return;
      }

      captures.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.id;
        const dur = c.duration_s ? `(${Math.round(c.duration_s)}s, ${c.frames_count} frames)` : `(${c.frames_count} frames)`;
        opt.textContent = `${c.id} ${dur} ${c.has_audit ? '✓ Audited' : ''}`;
        captureSelect.appendChild(opt);
      });

      selectCapture(captures[0].id);
    } catch (err) {
      captureSelect.innerHTML = '<option value="">Error loading captures</option>';
    }
  }

  async function selectCapture(id) {
    currentCaptureId = id;
    auditRecord.event_id = id;
    currentRecognition = null;
    hudCard.style.display = 'none';

    try {
      const res = await fetch(`/api/captures?id=${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error('Failed to load capture');
      const data = await res.json();
      frames = data.frames || [];

      // Restore saved audit if present
      if (data.audit) {
        Object.assign(auditRecord, data.audit);
      } else {
        // Reset milestones
        Object.keys(auditRecord.milestones).forEach(k => auditRecord.milestones[k] = null);
        // Check local storage draft
        const draft = localStorage.getItem(`audit_${id}`);
        if (draft) {
          try { Object.assign(auditRecord, JSON.parse(draft)); } catch(e){}
        }
      }

      updateMilestonesUI();
      boatsInInput.value = auditRecord.boats.inbound || 0;
      boatsOutInput.value = auditRecord.boats.outbound || 0;
      notesInput.value = auditRecord.reviewer_notes || '';

      frameSlider.min = 0;
      frameSlider.max = Math.max(0, frames.length - 1);
      currentFrameIdx = 0;
      renderFrame(0);
    } catch (err) {
      alert(`Could not load capture: ${err.message}`);
    }
  }

  // Render video frame on canvas
  function renderFrame(idx) {
    if (!frames || frames.length === 0) return;
    currentFrameIdx = Math.max(0, Math.min(frames.length - 1, idx));
    frameSlider.value = currentFrameIdx;
    frameCounter.textContent = `${currentFrameIdx + 1} / ${frames.length}`;

    const frame = frames[currentFrameIdx];
    const d = new Date(frame.ts * 1000);
    frameTs.textContent = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });

    const img = new Image();
    img.onload = () => {
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      if (currentRecognition) {
        drawHUD(currentRecognition);
      }
    };
    img.src = frame.src;
  }

  // Draw HUD overlay on canvas
  function drawHUD(rec) {
    const colorMap = {
      vehicle: '#f97316',
      vessel: '#38bdf8',
      pedestrian: '#10b981',
      bicycle: '#a855f7',
    };

    (rec.objects || []).forEach(obj => {
      const color = colorMap[obj.kind] || '#e2e8f0';
      const [x1, y1, x2, y2] = obj.box;
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

      ctx.fillStyle = color;
      ctx.font = 'bold 14px monospace';
      const tag = `${obj.kind.toUpperCase()} ${Math.round(obj.score * 100)}%`;
      ctx.fillText(tag, x1, Math.max(18, y1 - 6));
    });
  }

  // Run on-demand recognition
  async function runRecognition() {
    if (!frames || frames.length === 0) return;
    const frame = frames[currentFrameIdx];
    recognizeBtn.textContent = 'Analyzing...';

    try {
      const res = await fetch('/api/captures?action=recognize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: currentCaptureId, frame: frame.name }),
      });
      if (!res.ok) throw new Error('Recognition service failed');
      const rec = await res.json();
      currentRecognition = rec;
      renderFrame(currentFrameIdx);

      hudLatency.textContent = `${rec.latency_ms}ms`;
      const c = rec.counts || {};
      const infra = rec.infrastructure || {};
      hudBody.innerHTML = `
        <div style="display:flex; gap:1rem; margin-bottom:0.4rem">
          <span>Vehicles: <strong>${c.vehicle || 0}</strong></span>
          <span>Vessels: <strong>${c.vessel || 0}</strong></span>
          <span>Pedestrians: <strong>${c.pedestrian || 0}</strong></span>
          <span>Bicycles: <strong>${c.bicycle || 0}</strong></span>
        </div>
        <div>
          Bridge State: <strong>${infra.leaf_state || 'down'} (${infra.percent_open || 0}% open)</strong> · Gates: <strong>${(infra.gate_state || 'unknown').toUpperCase()}</strong>
        </div>
      `;
      hudCard.style.display = 'block';
    } catch (err) {
      alert(`Recognition failed: ${err.message}`);
    } finally {
      recognizeBtn.textContent = '⚡ Recognize (R)';
    }
  }

  // Update milestone labels
  function updateMilestonesUI() {
    document.querySelectorAll('.milestone-btn').forEach(btn => {
      const key = btn.dataset.milestone;
      const ts = auditRecord.milestones[key];
      const span = document.getElementById(`ms_${key}`);
      if (ts) {
        btn.classList.add('set');
        span.textContent = new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 2 });
      } else {
        btn.classList.remove('set');
        span.textContent = '--';
      }
    });
  }

  // Milestone Click Handler
  document.querySelectorAll('.milestone-btn').forEach(btn => {
    btn.onclick = () => {
      if (!frames || frames.length === 0) return;
      const key = btn.dataset.milestone;
      const curTs = frames[currentFrameIdx].ts;

      if (auditRecord.milestones[key] === curTs) {
        auditRecord.milestones[key] = null; // Toggle unset
      } else {
        auditRecord.milestones[key] = curTs;
      }

      updateMilestonesUI();
      saveDraft();
    };
  });

  function saveDraft() {
    auditRecord.boats.inbound = parseInt(boatsInInput.value, 10) || 0;
    auditRecord.boats.outbound = parseInt(boatsOutInput.value, 10) || 0;
    auditRecord.reviewer_notes = notesInput.value;
    localStorage.setItem(`audit_${currentCaptureId}`, JSON.stringify(auditRecord));
    saveStatus.textContent = 'Draft Saved';
    saveStatus.style.color = 'var(--accent-blue)';
  }

  // Certify and commit to SQLite
  saveAuditBtn.onclick = async () => {
    saveDraft();
    saveStatus.textContent = 'Committing...';
    try {
      const res = await fetch(`/api/captures?id=${encodeURIComponent(currentCaptureId)}&action=audit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(auditRecord),
      });
      if (!res.ok) throw new Error('Failed to commit audit');
      saveStatus.textContent = '✓ Certified & Saved';
      saveStatus.style.color = 'var(--accent-green)';
    } catch (err) {
      saveStatus.textContent = 'Save Failed';
      saveStatus.style.color = 'var(--accent-red)';
      alert(err.message);
    }
  };

  // Export Golden Benchmark Record
  exportGoldenBtn.onclick = () => {
    saveDraft();
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(jsonPretty(auditRecord));
    const dlAnchor = document.createElement('a');
    dlAnchor.setAttribute("href", dataStr);
    dlAnchor.setAttribute("download", `${currentCaptureId}.golden.json`);
    document.body.appendChild(dlAnchor);
    dlAnchor.click();
    dlAnchor.remove();
  };

  function jsonPretty(obj) {
    return JSON.stringify(obj, null, 2);
  }

  // Scrubber & Playback
  frameSlider.oninput = () => {
    currentRecognition = null;
    renderFrame(parseInt(frameSlider.value, 10));
  };

  prevFrameBtn.onclick = () => renderFrame(currentFrameIdx - 1);
  nextFrameBtn.onclick = () => renderFrame(currentFrameIdx + 1);

  playBtn.onclick = () => {
    if (isPlaying) {
      clearInterval(playInterval);
      playBtn.textContent = '▶ Play';
      isPlaying = false;
    } else {
      playBtn.textContent = '⏸ Pause';
      isPlaying = true;
      playInterval = setInterval(() => {
        if (currentFrameIdx >= frames.length - 1) {
          clearInterval(playInterval);
          playBtn.textContent = '▶ Play';
          isPlaying = false;
        } else {
          renderFrame(currentFrameIdx + 1);
        }
      }, 100);
    }
  };

  // Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    if (e.key === 'ArrowLeft' || e.key === 'j') {
      renderFrame(currentFrameIdx - 1);
    } else if (e.key === 'ArrowRight' || e.key === 'l') {
      renderFrame(currentFrameIdx + 1);
    } else if (e.key === ' ' || e.key === 'k') {
      e.preventDefault();
      playBtn.click();
    } else if (e.key === 'r' || e.key === 'R') {
      runRecognition();
    }
  });

  captureSelect.onchange = () => selectCapture(captureSelect.value);
  recognizeBtn.onclick = runRecognition;
  boatsInInput.onchange = saveDraft;
  boatsOutInput.onchange = saveDraft;
  notesInput.onchange = saveDraft;

  loadCaptures();
})();
