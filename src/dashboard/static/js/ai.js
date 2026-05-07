/**
 * ai.js — AI Insights UI component (Mobile-First)
 *
 * Design principles:
 *   - Gradient confidence bar: Red→Yellow→Green (nhận diện tức thì, không cần đọc số)
 *   - Touch targets: min 44×44px cho Like/Dislike (tránh chạm nhầm)
 *   - Background tints: xanh nhạt=Approve, đỏ nhạt=Reject (visual hierarchy)
 *   - Micro-interactions: scale + checkmark thay vì popup (không choán màn hình)
 *   - 5-second decision: thông tin quan trọng nhất ở trên cùng, rõ ràng
 */

// ── Color tokens ──────────────────────────────────────────────────────────────

const AI_THEME = {
  approve: {
    bg:         'rgba(14,203,129,0.08)',
    bgStrong:   'rgba(14,203,129,0.18)',
    border:     'rgba(14,203,129,0.35)',
    text:       '#0ecb81',
    badgeBg:    'rgba(14,203,129,0.15)',
    icon:       '✅',
    label:      'APPROVE',
  },
  reject: {
    bg:         'rgba(246,70,93,0.08)',
    bgStrong:   'rgba(246,70,93,0.18)',
    border:     'rgba(246,70,93,0.35)',
    text:       '#f6465d',
    badgeBg:    'rgba(246,70,93,0.15)',
    icon:       '❌',
    label:      'REJECT',
  },
  skip: {
    bg:         'rgba(136,146,164,0.06)',
    bgStrong:   'rgba(136,146,164,0.12)',
    border:     'rgba(136,146,164,0.2)',
    text:       '#8892a4',
    badgeBg:    'rgba(136,146,164,0.1)',
    icon:       '⏭️',
    label:      'SKIP',
  },
};

// ── Gradient confidence bar ───────────────────────────────────────────────────
// Dải màu liên tục: Đỏ (0) → Vàng (50) → Xanh lá (100)
// Người dùng nhận diện tức thì mà không cần đọc số.

function _renderGradientConfidenceBar(score) {
  if (score == null) {
    return '<span style="color:#8892a4;font-size:12px;">—</span>';
  }

  const pct = Math.max(0, Math.min(100, score));

  // Tính màu điểm hiện tại theo gradient Red→Yellow→Green
  // 0-50: đỏ → vàng, 50-100: vàng → xanh
  let r, g, b;
  if (pct <= 50) {
    const t = pct / 50;           // 0→1
    r = 246;                       // đỏ cố định
    g = Math.round(70 + t * 115); // 70→185
    b = Math.round(93 * (1 - t)); // 93→0
  } else {
    const t = (pct - 50) / 50;    // 0→1
    r = Math.round(246 * (1 - t) + 14 * t);  // 246→14
    g = Math.round(185 + t * 18);             // 185→203
    b = Math.round(0 + t * 129);              // 0→129
  }
  const dotColor = `rgb(${r},${g},${b})`;

  // Label màu theo ngưỡng
  const labelColor = pct >= 70 ? '#0ecb81' : pct >= 50 ? '#F0B90B' : '#f6465d';
  const labelText  = pct >= 70 ? 'Cao' : pct >= 50 ? 'Trung bình' : 'Thấp';

  return `
    <div style="display:flex;align-items:center;gap:10px;">
      <!-- Gradient track -->
      <div style="
        flex:1;
        height:8px;
        border-radius:6px;
        background:linear-gradient(to right, #f6465d 0%, #F0B90B 50%, #0ecb81 100%);
        position:relative;
        overflow:visible;
      ">
        <!-- Thumb indicator -->
        <div style="
          position:absolute;
          left:${pct}%;
          top:50%;
          transform:translate(-50%,-50%);
          width:14px;
          height:14px;
          border-radius:50%;
          background:${dotColor};
          border:2px solid #0b0e14;
          box-shadow:0 0 6px ${dotColor};
          transition:left 0.4s ease;
        "></div>
      </div>
      <!-- Score + label -->
      <div style="text-align:right;min-width:60px;">
        <span style="color:${labelColor};font-weight:700;font-size:13px;">${pct}</span>
        <span style="color:#8892a4;font-size:11px;">/100</span>
        <div style="color:${labelColor};font-size:10px;font-weight:600;letter-spacing:0.3px;">${labelText}</div>
      </div>
    </div>
  `;
}

// ── Main card renderer ────────────────────────────────────────────────────────

/**
 * Render AI Insights card với Mobile-First design.
 *
 * @param {number} tradeId
 * @param {object|null} aiInsights - {decision, confidence_score, analysis, latency_ms}
 * @param {string|null} existingRating - "like" | "dislike" | null
 * @returns {string} HTML string
 */
export function renderAIInsightsCard(tradeId, aiInsights, existingRating = null) {
  if (!aiInsights || !aiInsights.decision) {
    return '';  // Không render gì nếu không có AI data — giữ UI sạch
  }

  const { decision, confidence_score, analysis, latency_ms } = aiInsights;
  const theme = AI_THEME[decision] || AI_THEME.skip;

  const likeStyle    = _feedbackBtnStyle('like',    existingRating);
  const dislikeStyle = _feedbackBtnStyle('dislike', existingRating);

  // Latency badge (chỉ hiện khi có data)
  const latencyBadge = latency_ms
    ? `<span style="color:#8892a4;font-size:10px;margin-left:6px;">${Math.round(latency_ms)}ms</span>`
    : '';

  return `
    <div
      class="ai-insights-card"
      data-trade-id="${tradeId}"
      data-decision="${decision}"
      style="
        background:${theme.bg};
        border:1px solid ${theme.border};
        border-radius:10px;
        padding:14px 16px;
        margin-top:6px;
        transition:background 0.3s;
      "
    >
      <!-- ── Row 1: Header ── -->
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
        <div style="display:flex;align-items:center;gap:6px;">
          <span style="font-size:15px;">🤖</span>
          <span style="font-weight:700;font-size:13px;color:#e8eaf0;letter-spacing:0.2px;">AI Insights</span>
          ${latencyBadge}
        </div>
        <!-- Decision badge — màu nền rõ ràng, dễ nhận diện -->
        <div style="
          background:${theme.badgeBg};
          color:${theme.text};
          border:1px solid ${theme.border};
          padding:4px 12px;
          border-radius:20px;
          font-size:12px;
          font-weight:800;
          letter-spacing:0.8px;
          display:flex;align-items:center;gap:5px;
        ">
          <span>${theme.icon}</span>
          <span>${theme.label}</span>
        </div>
      </div>

      <!-- ── Row 2: Gradient confidence bar ── -->
      <div style="margin-bottom:12px;">
        <div style="
          display:flex;align-items:center;justify-content:space-between;
          margin-bottom:6px;
        ">
          <span style="color:#8892a4;font-size:10px;text-transform:uppercase;letter-spacing:0.6px;">
            Confidence
          </span>
        </div>
        ${_renderGradientConfidenceBar(confidence_score)}
      </div>

      <!-- ── Row 3: Analysis text ── -->
      ${analysis ? `
        <div style="
          background:rgba(0,0,0,0.25);
          border-left:3px solid ${theme.border};
          border-radius:0 6px 6px 0;
          padding:8px 12px;
          font-size:12px;
          color:#c8cdd8;
          line-height:1.6;
          margin-bottom:12px;
          font-style:italic;
        ">${analysis}</div>
      ` : ''}

      <!-- ── Row 4: Feedback — Touch-friendly 44×44px targets ── -->
      <div style="
        display:flex;align-items:center;gap:10px;
        border-top:1px solid rgba(255,255,255,0.06);
        padding-top:12px;
      ">
        <span style="color:#8892a4;font-size:11px;flex:1;">AI có chính xác không?</span>

        <!-- Like button: min 44×44px -->
        <button
          id="ai-like-${tradeId}"
          class="ai-feedback-btn"
          onclick="window.handleAIFeedback(${tradeId}, 'like')"
          title="AI đúng"
          style="${likeStyle}"
          aria-label="AI đúng"
        >👍</button>

        <!-- Dislike button: min 44×44px -->
        <button
          id="ai-dislike-${tradeId}"
          class="ai-feedback-btn"
          onclick="window.handleAIFeedback(${tradeId}, 'dislike')"
          title="AI sai"
          style="${dislikeStyle}"
          aria-label="AI sai"
        >👎</button>
      </div>
    </div>
  `;
}

// ── Button style helper ───────────────────────────────────────────────────────

function _feedbackBtnStyle(type, existingRating) {
  const isActive = existingRating === type;
  const activeColors = {
    like:    { bg: 'rgba(14,203,129,0.2)',  border: '#0ecb81', color: '#0ecb81' },
    dislike: { bg: 'rgba(246,70,93,0.2)',   border: '#f6465d', color: '#f6465d' },
  };
  const c = isActive ? activeColors[type] : null;

  return `
    min-width:44px;
    min-height:44px;
    width:44px;
    height:44px;
    display:flex;
    align-items:center;
    justify-content:center;
    background:${c ? c.bg : 'rgba(255,255,255,0.05)'};
    border:1px solid ${c ? c.border : 'rgba(255,255,255,0.1)'};
    color:${c ? c.color : '#8892a4'};
    border-radius:8px;
    cursor:pointer;
    font-size:18px;
    transition:all 0.2s ease;
    -webkit-tap-highlight-color:transparent;
    ${isActive ? 'box-shadow:0 0 8px ' + c.border + '40;' : ''}
  `.replace(/\s+/g, ' ').trim();
}

// ── Feedback handler với micro-interaction ────────────────────────────────────

/**
 * Xử lý feedback: Like gửi ngay, Dislike mở bottom sheet nhập comment.
 * Micro-interaction: scale + checkmark thay vì popup.
 *
 * @param {number} tradeId
 * @param {string} rating - "like" | "dislike"
 */
window.handleAIFeedback = async function(tradeId, rating) {
  if (rating === 'like') {
    await _doSubmitFeedback(tradeId, 'like', null);
  } else {
    _openDislikeSheet(tradeId);
  }
};

async function _doSubmitFeedback(tradeId, rating, comment) {
  // Micro-interaction: loading state
  const btn = document.getElementById(`ai-${rating}-${tradeId}`);
  if (btn) {
    btn.style.opacity = '0.5';
    btn.style.transform = 'scale(0.9)';
    btn.disabled = true;
  }

  try {
    const resp = await fetch('/api/ai/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_id: tradeId, rating, comment: comment || null }),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    // Micro-interaction: success — scale up + checkmark, không dùng popup
    _applySuccessMicroInteraction(tradeId, rating);

  } catch (err) {
    console.error('[AI] feedback error:', err);
    // Restore button on error
    if (btn) {
      btn.style.opacity = '1';
      btn.style.transform = 'scale(1)';
      btn.disabled = false;
    }
    _showInlineError(tradeId);
  }
}

function _applySuccessMicroInteraction(tradeId, rating) {
  const likeBtn    = document.getElementById(`ai-like-${tradeId}`);
  const dislikeBtn = document.getElementById(`ai-dislike-${tradeId}`);
  if (!likeBtn || !dislikeBtn) return;

  const activeColors = {
    like:    { bg: 'rgba(14,203,129,0.2)',  border: '#0ecb81', color: '#0ecb81', shadow: '#0ecb8140' },
    dislike: { bg: 'rgba(246,70,93,0.2)',   border: '#f6465d', color: '#f6465d', shadow: '#f6465d40' },
  };
  const inactiveStyle = {
    bg: 'rgba(255,255,255,0.03)', border: 'rgba(255,255,255,0.08)', color: '#8892a4', shadow: 'none',
  };

  const activeBtn   = rating === 'like' ? likeBtn    : dislikeBtn;
  const inactiveBtn = rating === 'like' ? dislikeBtn : likeBtn;
  const c = activeColors[rating];

  // Active button: scale up + glow
  activeBtn.style.cssText = _feedbackBtnStyle(rating, rating);
  activeBtn.style.transform = 'scale(1.15)';
  activeBtn.style.boxShadow = `0 0 12px ${c.shadow}`;
  activeBtn.disabled = false;
  setTimeout(() => {
    activeBtn.style.transform = 'scale(1.0)';
  }, 200);

  // Inactive button: dim
  inactiveBtn.style.background  = inactiveStyle.bg;
  inactiveBtn.style.borderColor = inactiveStyle.border;
  inactiveBtn.style.color       = inactiveStyle.color;
  inactiveBtn.style.opacity     = '0.5';
  inactiveBtn.disabled = false;

  // Cập nhật card background tint nhẹ hơn để xác nhận đã feedback
  const card = document.querySelector(
    `.ai-insights-card[data-trade-id="${tradeId}"]`
  );
  if (card) {
    const decision = card.dataset.decision;
    const theme = AI_THEME[decision] || AI_THEME.skip;
    card.style.background = theme.bgStrong;
    setTimeout(() => { card.style.background = theme.bg; }, 800);
  }
}

function _showInlineError(tradeId) {
  const card = document.querySelector(`.ai-insights-card[data-trade-id="${tradeId}"]`);
  if (!card) return;
  const errEl = document.createElement('div');
  errEl.style.cssText = `
    color:#f6465d;font-size:11px;text-align:center;
    padding:4px;margin-top:4px;
  `;
  errEl.textContent = '⚠️ Lỗi gửi phản hồi — thử lại';
  card.appendChild(errEl);
  setTimeout(() => errEl.remove(), 3000);
}

// ── Comment sanitizer (client-side, lightweight) ─────────────────────────────
// Dùng DOMParser để strip HTML tags — không cần thư viện ngoài.
// Backend vẫn là tuyến phòng thủ chính; đây chỉ là UX improvement.

const _COMMENT_MAX_LEN = 500;

/**
 * Strip HTML tags khỏi chuỗi bằng DOMParser (an toàn, không eval).
 * @param {string} raw
 * @returns {string} text thuần, không có HTML
 */
function _sanitizeComment(raw) {
  if (!raw) return '';
  // DOMParser parse HTML và lấy textContent — loại bỏ mọi tag
  const doc = new DOMParser().parseFromString(raw, 'text/html');
  return (doc.body.textContent || '').trim();
}

// ── Dislike bottom sheet (mobile-friendly) ────────────────────────────────────

function _openDislikeSheet(tradeId) {
  const existing = document.getElementById('ai-dislike-sheet');
  if (existing) existing.remove();

  const sheet = document.createElement('div');
  sheet.id = 'ai-dislike-sheet';
  sheet.style.cssText = `
    position:fixed;bottom:0;left:0;right:0;z-index:9999;
    background:#1a1f2e;
    border-top:1px solid rgba(255,255,255,0.1);
    border-radius:16px 16px 0 0;
    padding:20px 20px 32px;
    box-shadow:0 -8px 32px rgba(0,0,0,0.5);
    animation:slideUp 0.25s ease;
    max-width:600px;
    margin:0 auto;
  `;
  sheet.innerHTML = `
    <!-- Drag handle -->
    <div style="
      width:40px;height:4px;background:rgba(255,255,255,0.15);
      border-radius:2px;margin:0 auto 16px;
    "></div>

    <div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">
      <span style="font-size:20px;">👎</span>
      <h3 style="color:#e8eaf0;font-size:16px;font-weight:700;">AI đã sai ở đâu?</h3>
    </div>

    <p style="color:#8892a4;font-size:13px;margin-bottom:12px;line-height:1.5;">
      Ghi chú ngắn giúp cải thiện AI (tùy chọn):
    </p>

    <textarea
      id="ai-dislike-comment"
      placeholder="Ví dụ: Bỏ qua divergence MACD, thị trường sideway..."
      maxlength="${_COMMENT_MAX_LEN}"
      style="
        width:100%;height:72px;
        background:rgba(0,0,0,0.3);
        border:1px solid rgba(255,255,255,0.1);
        border-radius:8px;
        color:#e8eaf0;padding:10px 12px;
        font-size:14px;resize:none;
        font-family:inherit;
        -webkit-appearance:none;
        outline:none;
        box-sizing:border-box;
        transition:border-color 0.2s;
      "
    ></textarea>

    <!-- Character counter: 0/500, đỏ khi gần giới hạn -->
    <div style="
      display:flex;justify-content:flex-end;
      margin-top:4px;margin-bottom:12px;
    ">
      <span
        id="ai-char-counter"
        style="font-size:11px;color:#8892a4;transition:color 0.2s;"
      >0 / ${_COMMENT_MAX_LEN}</span>
    </div>

    <!-- Touch-friendly action buttons: min 48px height -->
    <div style="display:flex;gap:10px;">
      <button
        id="ai-sheet-cancel"
        onclick="document.getElementById('ai-dislike-sheet').remove();
                 document.getElementById('ai-sheet-backdrop').remove();"
        style="
          flex:1;min-height:48px;
          background:rgba(255,255,255,0.05);
          border:1px solid rgba(255,255,255,0.1);
          color:#8892a4;border-radius:10px;
          cursor:pointer;font-size:14px;font-weight:600;
          -webkit-tap-highlight-color:transparent;
        "
      >Hủy</button>
      <button
        id="ai-sheet-submit"
        onclick="window._submitDislikeFromSheet(${tradeId})"
        style="
          flex:2;min-height:48px;
          background:rgba(246,70,93,0.15);
          border:1px solid #f6465d;
          color:#f6465d;border-radius:10px;
          cursor:pointer;font-size:14px;font-weight:700;
          -webkit-tap-highlight-color:transparent;
          transition:opacity 0.2s;
        "
      >Gửi phản hồi 👎</button>
    </div>
  `;

  document.body.appendChild(sheet);

  // Backdrop để đóng sheet khi tap ngoài
  const backdrop = document.createElement('div');
  backdrop.id = 'ai-sheet-backdrop';
  backdrop.style.cssText = `
    position:fixed;top:0;left:0;right:0;bottom:0;
    background:rgba(0,0,0,0.5);z-index:9998;
  `;
  backdrop.onclick = () => {
    sheet.remove();
    backdrop.remove();
  };
  document.body.insertBefore(backdrop, sheet);

  // ── Character counter + validation ───────────────────────────────────────
  const textarea   = document.getElementById('ai-dislike-comment');
  const counter    = document.getElementById('ai-char-counter');
  const submitBtn  = document.getElementById('ai-sheet-submit');

  function _updateCounter() {
    const len      = textarea.value.length;
    const isOver   = len > _COMMENT_MAX_LEN;
    const isNearLimit = len > _COMMENT_MAX_LEN * 0.9;  // > 450 chars
    const isEmpty  = textarea.value.trim().length === 0 && len > 0;

    // Cập nhật counter text và màu
    counter.textContent = `${len} / ${_COMMENT_MAX_LEN}`;
    if (isOver) {
      counter.style.color = '#f6465d';       // Đỏ: vượt giới hạn
      textarea.style.borderColor = '#f6465d';
    } else if (isNearLimit) {
      counter.style.color = '#F0B90B';       // Vàng: gần giới hạn
      textarea.style.borderColor = 'rgba(240,185,11,0.4)';
    } else {
      counter.style.color = '#8892a4';       // Xám: bình thường
      textarea.style.borderColor = 'rgba(255,255,255,0.1)';
    }

    // Disable nút nếu: vượt giới hạn HOẶC chỉ có whitespace (không rỗng)
    const shouldDisable = isOver || isEmpty;
    submitBtn.disabled = shouldDisable;
    submitBtn.style.opacity = shouldDisable ? '0.4' : '1';
    submitBtn.style.cursor  = shouldDisable ? 'not-allowed' : 'pointer';
  }

  textarea.addEventListener('input', _updateCounter);
  textarea.focus();
}

window._submitDislikeFromSheet = async function(tradeId) {
  const raw     = document.getElementById('ai-dislike-comment')?.value || '';
  const comment = _sanitizeComment(raw) || null;  // strip HTML trước khi gửi
  document.getElementById('ai-dislike-sheet')?.remove();
  document.getElementById('ai-sheet-backdrop')?.remove();
  await _doSubmitFeedback(tradeId, 'dislike', comment);
};

// ── AI Stats panel ────────────────────────────────────────────────────────────

export async function loadAIStats() {
  const panel = document.getElementById('aiStatsPanel');
  if (!panel) return;
  try {
    const stats = await fetch('/api/ai/stats').then(r => r.json());
    _renderAIStats(panel, stats);
  } catch {
    panel.innerHTML = '<span style="color:#8892a4;font-size:13px;">Không thể tải AI stats</span>';
  }
}

function _renderAIStats(panel, s) {
  const wr = s.approve_win_rate_pct;
  const fa = s.feedback_accuracy_pct;

  const wrColor = wr == null ? '#8892a4' : wr >= 60 ? '#0ecb81' : wr >= 40 ? '#F0B90B' : '#f6465d';
  const faColor = fa == null ? '#8892a4' : fa >= 70 ? '#0ecb81' : fa >= 50 ? '#F0B90B' : '#f6465d';

  panel.innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;">
      ${_statCard('🤖 Đã phân tích', s.total_ai_analyzed, '#e8eaf0')}
      ${_statCard('✅ Approve', s.total_approve, '#0ecb81')}
      ${_statCard('❌ Reject', s.total_reject, '#f6465d')}
      ${_statCard('🏆 Win-rate (Approve)', wr != null ? wr + '%' : '—', wrColor)}
      ${_statCard('👍 Feedback Accuracy', fa != null ? fa + '%' : '—', faColor)}
      ${_statCard('💬 Phản hồi', s.total_feedback, '#8892a4')}
    </div>
  `;
}

function _statCard(label, value, color) {
  return `
    <div style="
      background:var(--bg-panel);
      border:1px solid var(--border);
      border-radius:8px;padding:14px;text-align:center;
    ">
      <div style="color:#8892a4;font-size:11px;margin-bottom:6px;
        text-transform:uppercase;letter-spacing:0.4px;">${label}</div>
      <div style="font-size:20px;font-weight:700;color:${color};">${value}</div>
    </div>
  `;
}

// ── Expose to window ──────────────────────────────────────────────────────────

window.submitAIFeedback    = _doSubmitFeedback;
window.openAIFeedbackModal = _openDislikeSheet;  // backward compat alias
