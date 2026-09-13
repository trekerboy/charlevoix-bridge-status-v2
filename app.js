/* Dashboard client application for Charlevoix Memorial Bridge */
(function() {
  let selectedDate = null;
  let isHistorical = false;
  let pollInterval = null;
  let currentStats = null;

  const liveImg = document.getElementById('liveImg');
  const videoTime = document.getElementById('videoTime');
  const stateBanner = document.getElementById('stateBanner');
  const leafAngleVal = document.getElementById('leafAngleVal');
  const leafOpenVal = document.getElementById('leafOpenVal');
  const gateStateVal = document.getElementById('gateStateVal');
  const readingFreshness = document.getElementById('readingFreshness');
  const vehTodayVal = document.getElementById('vehTodayVal');
  const boatTodayVal = document.getElementById('boatTodayVal');
  const pedTodayVal = document.getElementById('pedTodayVal');
  const bikeTodayVal = document.getElementById('bikeTodayVal');
  const scheduleGrid = document.getElementById('scheduleGrid');
  const offScheduleSection = document.getElementById('offScheduleSection');
  const offScheduleGrid = document.getElementById('offScheduleGrid');
  const dateSelect = document.getElementById('dateSelect');
  const prevDateBtn = document.getElementById('prevDateBtn');
  const nextDateBtn = document.getElementById('nextDateBtn');
  const liveNowBtn = document.getElementById('liveNowBtn');
  const livePill = document.getElementById('livePill');
  const fullscreenBtn = document.getElementById('fullscreenBtn');
  const videoContainer = document.getElementById('videoContainer');
  const openingDetailModal = document.getElementById('openingDetailModal');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  const closeModalBtn = document.getElementById('closeModalBtn');
  const hourlyChartContainer = document.getElementById('hourlyChartContainer');

  // 1. Sub-second Live Camera Stream Loop (<1s latency)
  function startLiveStream() {
    setInterval(() => {
      if (!isHistorical && document.visibilityState === 'visible') {
        const bust = Date.now();
        const nextImg = new Image();
        nextImg.onload = () => {
          liveImg.src = nextImg.src;
          const now = new Date();
          videoTime.textContent = now.toLocaleTimeString();
        };
        nextImg.src = `/api/live?t=${bust}`;
      }
    }, 850);
  }

  // 2. Telemetry Poller
  async function fetchStats() {
    try {
      const url = selectedDate ? `/api/stats?date=${encodeURIComponent(selectedDate)}` : '/api/stats';
      const res = await fetch(url);
      if (!res.ok) throw new Error('API unavailable');
      const data = await res.json();
      currentStats = data;
      renderStats(data);
    } catch (err) {
      readingFreshness.textContent = 'Connection Disconnected';
      readingFreshness.style.color = 'var(--accent-red)';
    }
  }

  // 3. Render Telemetry
  function renderStats(data) {
    isHistorical = data.is_historical;

    // Date navigation state
    if (isHistorical) {
      livePill.textContent = 'Archive View';
      livePill.style.color = 'var(--accent-amber)';
      livePill.style.borderColor = 'rgba(245, 158, 11, 0.4)';
      liveNowBtn.style.display = 'inline-block';
    } else {
      livePill.textContent = 'Live Telemetry';
      livePill.style.color = 'var(--accent-green)';
      livePill.style.borderColor = 'rgba(16, 185, 129, 0.4)';
      liveNowBtn.style.display = 'none';
    }

    // Populate date selector if needed
    if (data.available_dates && dateSelect.options.length <= 1) {
      dateSelect.innerHTML = '';
      data.available_dates.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d;
        opt.textContent = d;
        if (d === data.selected_date) opt.selected = true;
        dateSelect.appendChild(opt);
      });
    }

    // Status Banner
    const state = (data.state || 'closed').toLowerCase();
    stateBanner.className = 'state-badge-lg';
    if (state === 'closed' || state === 'down') {
      stateBanner.textContent = 'CLOSED / SEATED';
      stateBanner.classList.add('state-closed');
    } else if (state === 'moving') {
      stateBanner.textContent = 'LEAF IN TRANSIT';
      stateBanner.classList.add('state-moving');
    } else {
      stateBanner.textContent = 'OPEN / TRAFFIC BLOCKED';
      stateBanner.classList.add('state-open');
    }

    leafAngleVal.textContent = `${data.leaf_angle_deg || 0}°`;
    leafOpenVal.textContent = `${data.percent_open || 0}%`;
    gateStateVal.textContent = (data.gate_state || 'unknown').toUpperCase();

    if (data.fresh) {
      readingFreshness.textContent = '● Real-Time Feed';
      readingFreshness.style.color = 'var(--accent-green)';
    } else {
      readingFreshness.textContent = isHistorical ? 'Historical Record' : 'Stale';
      readingFreshness.style.color = 'var(--text-dim)';
    }

    // Crossing Totals
    const win = data.windows && data.windows.today ? data.windows.today : {};
    const veh = win.vehicles || {};
    const totalVeh = (veh.northbound || 0) + (veh.southbound || 0);
    const boats = win.boats || {};
    const totalBoats = (boats.inbound || 0) + (boats.outbound || 0);

    vehTodayVal.textContent = totalVeh.toLocaleString();
    boatTodayVal.textContent = totalBoats.toLocaleString();
    pedTodayVal.textContent = (win.pedestrians || 0).toLocaleString();
    bikeTodayVal.textContent = (win.bicycles || 0).toLocaleString();

    // 33-Slot Schedule Grid
    renderSchedule(data.schedule_slots || [], data.openings || []);

    // Off-Schedule Lifts
    renderOffSchedule(data.off_schedule_openings || []);

    // 24-Hour Hourly Chart
    renderHourlyChart(data.hourly_traffic || []);
  }

  function renderSchedule(slots, openings) {
    scheduleGrid.innerHTML = '';
    slots.forEach(slot => {
      const cell = document.createElement('div');
      cell.className = `slot-cell ${slot.status || 'uncalled'}`;
      let statusText = 'No Lift';
      if (slot.status === 'opened') statusText = '✓ Opened';
      else if (slot.status === 'in-window') statusText = 'In Window';
      else if (slot.status === 'upcoming') statusText = 'Upcoming';

      cell.innerHTML = `
        <div class="slot-time">${slot.label}</div>
        <div class="slot-status">${statusText}</div>
      `;

      if (slot.opening) {
        cell.onclick = () => showOpeningModal(slot.opening);
      }
      scheduleGrid.appendChild(cell);
    });
  }

  function renderOffSchedule(openings) {
    if (!openings || openings.length === 0) {
      offScheduleSection.style.display = 'none';
      return;
    }
    offScheduleSection.style.display = 'block';
    offScheduleGrid.innerHTML = '';
    openings.forEach(op => {
      const card = document.createElement('div');
      card.className = 'off-card';
      const tStr = new Date(op.lift_start * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const gradeLetter = (op.grade && op.grade.letter) ? op.grade.letter : 'A';
      card.innerHTML = `
        <div class="off-card-title">⚡ ${tStr} · Commercial Opening</div>
        <div style="font-size:0.75rem; color:var(--text-muted); margin-top:0.25rem">
          Duration: ${Math.round(op.road_closure_s || op.total_s || 0)}s · Boats: ${(op.boats_in || 0) + (op.boats_out || 0)} · Grade: <strong>${gradeLetter}</strong>
        </div>
      `;
      card.onclick = () => showOpeningModal(op);
      offScheduleGrid.appendChild(card);
    });
  }

  function showOpeningModal(op) {
    modalTitle.textContent = `Opening Event Details (${new Date(op.lift_start * 1000).toLocaleTimeString()})`;
    const grade = op.grade || {};
    const totalBoats = (op.boats_in || 0) + (op.boats_out || 0);

    modalBody.innerHTML = `
      <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:0.75rem; margin-bottom:1rem">
        <div class="metric-box">
          <div class="metric-val" style="color:var(--accent-blue)">${grade.letter || 'A'}</div>
          <div class="metric-lbl">Academic Grade (${grade.score || 100}/100)</div>
        </div>
        <div class="metric-box">
          <div class="metric-val">${Math.round(op.road_closure_s || op.total_s || 0)}s</div>
          <div class="metric-lbl">Total Road Closure</div>
        </div>
        <div class="metric-box">
          <div class="metric-val">${Math.round(op.pre_opening_wait_s || 0)}s</div>
          <div class="metric-lbl">Pre-Lift Gate Wait</div>
        </div>
        <div class="metric-box">
          <div class="metric-val">${totalBoats}</div>
          <div class="metric-lbl">Marine Vessels (${op.boats_in || 0} In / ${op.boats_out || 0} Out)</div>
        </div>
      </div>
      <div style="font-size:0.85rem; color:var(--text-muted); background:var(--bg-card); padding:0.75rem; border-radius:6px">
        <strong>Evaluation:</strong> ${grade.summary || 'Punctual opening with swift clearance.'}
      </div>
    `;
    openingDetailModal.style.display = 'block';
    openingDetailModal.scrollIntoView({ behavior: 'smooth' });
  }

  closeModalBtn.onclick = () => {
    openingDetailModal.style.display = 'none';
  };

  // 4. Render 24-Hour Hourly Traffic Volume SVG Chart
  function renderHourlyChart(hourly) {
    if (!hourly || hourly.length === 0) return;
    const maxVal = Math.max(10, ...hourly.map(h => {
      const v = (h.vehicles.northbound || 0) + (h.vehicles.southbound || 0);
      const b = (h.boats.inbound || 0) + (h.boats.outbound || 0);
      return v + (h.pedestrians || 0) + b;
    }));

    const svgH = 180;
    const svgW = 1000;
    const barW = (svgW / 24) - 8;

    let barsSvg = '';
    hourly.forEach((h, i) => {
      const v = (h.vehicles.northbound || 0) + (h.vehicles.southbound || 0);
      const b = (h.boats.inbound || 0) + (h.boats.outbound || 0);
      const p = h.pedestrians || 0;
      const tot = v + b + p;

      const barH = (tot / maxVal) * (svgH - 40);
      const x = i * (svgW / 24) + 4;
      const y = (svgH - 25) - barH;

      const hrLabel = i === 0 ? '12A' : (i === 12 ? '12P' : (i > 12 ? `${i-12}P` : `${i}A`));

      barsSvg += `
        <g class="bar-group" cursor="pointer">
          <title>${hrLabel}: ${v} vehicles, ${p} pedestrians, ${b} vessels</title>
          <rect x="${x}" y="${y}" width="${barW}" height="${barH}" fill="var(--accent-blue)" rx="3" opacity="0.85"/>
          <text x="${x + barW/2}" y="${svgH - 8}" fill="var(--text-dim)" font-size="11" text-anchor="middle">${hrLabel}</text>
        </g>
      `;
    });

    hourlyChartContainer.innerHTML = `
      <svg viewBox="0 0 ${svgW} ${svgH}" width="100%" height="100%" style="overflow:visible">
        ${barsSvg}
      </svg>
    `;
  }

  // 5. Date Navigation Event Handlers
  dateSelect.onchange = () => {
    selectedDate = dateSelect.value;
    const url = new URL(window.location);
    url.searchParams.set('date', selectedDate);
    window.history.pushState({}, '', url);
    fetchStats();
  };

  prevDateBtn.onclick = () => {
    if (dateSelect.selectedIndex < dateSelect.options.length - 1) {
      dateSelect.selectedIndex += 1;
      dateSelect.onchange();
    }
  };

  nextDateBtn.onclick = () => {
    if (dateSelect.selectedIndex > 0) {
      dateSelect.selectedIndex -= 1;
      dateSelect.onchange();
    }
  };

  liveNowBtn.onclick = () => {
    selectedDate = null;
    const url = new URL(window.location);
    url.searchParams.delete('date');
    window.history.pushState({}, '', url);
    fetchStats();
  };

  fullscreenBtn.onclick = () => {
    if (!document.fullscreenElement) {
      videoContainer.requestFullscreen().catch(err => alert(err.message));
    } else {
      document.exitFullscreen();
    }
  };

  // Check URL params on load
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('date')) {
    selectedDate = urlParams.get('date');
  }

  // Start polling
  fetchStats();
  pollInterval = setInterval(fetchStats, 2000);
  startLiveStream();
})();
