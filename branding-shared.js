// ── BRANDING SHARED — used by cloud.html and branding.html ──────────────────

const BUCKET = 'uploads';

const ACCENT_PRESETS = ['#8B6F47','#1C1917','#2563EB','#059669','#DC2626','#7C3AED','#EA580C','#0891B2'];
const BG_PRESETS = [
  { hex:'#F5F0E8', label:'Warm' }, { hex:'#FFFFFF', label:'White' },
  { hex:'#1C1917', label:'Dark' }, { hex:'#EFF6FF', label:'Cool'  }, { hex:'#F0FDF4', label:'Mint' }
];

let _branding = { brand_name:'', tagline:'', domain_url:'', accent_color:'#8B6F47', bg_color:'#F5F0E8', logo_url:null };
let _brandingLoaded = false;
let _wallpapers = [];
let _logoUrl  = null;   // current logo URL (saved or object URL for new pick)
let _logoFile = null;   // File object waiting to be uploaded on Save

function isColorDark(hex) {
  try {
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    return (0.299*r + 0.587*g + 0.114*b) < 140;
  } catch { return false; }
}

function initBrandingSwatches() {
  const ac = document.getElementById('accent-swatches');
  if (ac.children.length) return;
  ACCENT_PRESETS.forEach(hex => {
    const btn = document.createElement('button');
    btn.dataset.swatchType = 'accent'; btn.dataset.color = hex;
    btn.onclick = () => setAccentColor(hex);
    btn.title = hex;
    btn.style.cssText = `width:28px;height:28px;border-radius:8px;background:${hex};border:none;cursor:pointer;transition:all .15s;flex-shrink:0`;
    ac.appendChild(btn);
  });
  const bg = document.getElementById('bg-swatches');
  BG_PRESETS.forEach(({ hex, label }) => {
    const btn = document.createElement('button');
    btn.dataset.swatchType = 'bg'; btn.dataset.color = hex;
    btn.onclick = () => setBgColor(hex);
    btn.title = label;
    btn.style.cssText = `width:28px;height:28px;border-radius:8px;background:${hex};border:1px solid rgba(28,25,23,0.18);cursor:pointer;transition:all .15s;flex-shrink:0`;
    bg.appendChild(btn);
  });
}

function updateSwatchSelection(type, selectedHex) {
  document.querySelectorAll('[data-swatch-type="' + type + '"]').forEach(btn => {
    const sel = btn.dataset.color.toLowerCase() === selectedHex.toLowerCase();
    btn.style.outline      = sel ? '2px solid #1C1917' : 'none';
    btn.style.outlineOffset = '2px';
    btn.style.transform    = sel ? 'scale(1.18)' : 'scale(1)';
  });
}

function setAccentColor(hex) {
  _branding.accent_color = hex;
  document.getElementById('brand-accent-input').value = hex;
  document.getElementById('brand-accent-hex').textContent = hex.toUpperCase();
  updateSwatchSelection('accent', hex);
  updateBrandPreview();
}

function setBgColor(hex) {
  _branding.bg_color = hex;
  updateSwatchSelection('bg', hex);
  updateBrandPreview();
}

function updateBrandPreview() {
  if (!document.getElementById('brand-preview-bg')) return;  // preview panel may be absent
  const name    = document.getElementById('brand-name')?.value.trim()    || 'Your Brand';
  const tagline = document.getElementById('brand-tagline')?.value.trim() || '';
  const domain  = document.getElementById('brand-domain')?.value.trim()  || '';
  const initial = name[0]?.toUpperCase() || 'F';
  const isDark  = isColorDark(_branding.bg_color);
  const text    = isDark ? '#F5F0E8'                    : '#1C1917';
  const sub     = isDark ? 'rgba(245,240,232,0.45)'     : 'rgba(28,25,23,0.4)';
  const cardBg  = isDark ? 'rgba(245,240,232,0.08)'     : 'rgba(28,25,23,0.06)';
  const footer  = isDark ? 'rgba(245,240,232,0.25)'     : 'rgba(28,25,23,0.3)';

  document.getElementById('brand-preview-bg').style.background = _branding.bg_color;
  document.getElementById('preview-logo').style.background     = _branding.accent_color;
  document.getElementById('preview-logo').textContent          = initial;
  document.getElementById('preview-name').textContent          = name;
  document.getElementById('preview-name').style.color          = text;
  document.getElementById('preview-btn-mock').style.background = _branding.accent_color;
  document.getElementById('preview-card').style.background     = cardBg;
  document.getElementById('preview-card-text').style.color     = text;
  document.getElementById('preview-card-meta').style.color     = sub;
  document.getElementById('preview-footer').style.color        = footer;

  const tagEl = document.getElementById('preview-tagline');
  tagEl.textContent = tagline; tagEl.style.display = tagline ? '' : 'none'; tagEl.style.color = sub;
  const domEl = document.getElementById('preview-domain');
  if (domEl) { domEl.textContent = domain; domEl.style.display = domain ? '' : 'none'; domEl.style.color = sub; }
}

async function loadBranding() {
  initBrandingSwatches();
  if (_brandingLoaded) { renderWallpaperSlots(); updateBrandPreview(); return; }
  const { data } = await _sb.from('user_branding').select('*').eq('user_id', currentUser.id).maybeSingle();
  if (data) {
    _branding.brand_name   = data.brand_name   || '';
    _branding.tagline      = data.tagline       || '';
    _branding.domain_url   = data.domain_url    || '';
    _branding.accent_color = data.accent_color  || '#8B6F47';
    _branding.bg_color     = data.bg_color      || '#F5F0E8';
    _branding.logo_url     = data.logo_url      || null;
    _logoUrl               = _branding.logo_url;
    _wallpapers = (data.wallpapers || []).map(wp =>
      typeof wp === 'string' ? { url: wp, type: 'image' } : wp
    );
  }
  document.getElementById('brand-name').value    = _branding.brand_name;
  document.getElementById('brand-tagline').value = _branding.tagline;
  document.getElementById('brand-domain').value  = _branding.domain_url;
  setAccentColor(_branding.accent_color);
  setBgColor(_branding.bg_color);
  renderWallpaperSlots();
  renderLogoPreview();
  updateBrandPreview();
  _brandingLoaded = true;
}

async function saveBranding() {
  // Upload logo if a new file was picked
  let savedLogoUrl = _branding.logo_url;
  if (_logoFile) {
    showToast('Uploading logo…', true);
    const ext  = _logoFile.type === 'image/jpeg' ? 'jpg' : 'png';
    const path = currentUser.id + '/branding/logo.' + ext;
    const { error: upErr } = await _sb.storage.from(BUCKET).upload(path, _logoFile, { contentType: _logoFile.type, upsert: true });
    if (upErr) { showToast('Logo upload failed: ' + upErr.message); return; }
    const { data: { publicUrl } } = _sb.storage.from(BUCKET).getPublicUrl(path);
    savedLogoUrl = publicUrl + '?t=' + Date.now(); // cache-bust
    _logoFile = null;
  }

  const record = {
    user_id:      currentUser.id,
    brand_name:   document.getElementById('brand-name').value.trim(),
    tagline:      document.getElementById('brand-tagline').value.trim(),
    domain_url:   document.getElementById('brand-domain').value.trim(),
    accent_color: _branding.accent_color,
    bg_color:     _branding.bg_color,
    logo_url:     savedLogoUrl,
    wallpapers:   _wallpapers,
    updated_at:   new Date().toISOString()
  };
  const { data: existing } = await _sb.from('user_branding').select('user_id').eq('user_id', currentUser.id).maybeSingle();
  const { error } = existing
    ? await _sb.from('user_branding').update(record).eq('user_id', currentUser.id)
    : await _sb.from('user_branding').insert(record);
  if (error) { showToast('Could not save: ' + error.message); return; }
  _branding.brand_name = record.brand_name;
  _branding.tagline    = record.tagline;
  _branding.domain_url = record.domain_url;
  _branding.logo_url   = savedLogoUrl;
  _logoUrl             = savedLogoUrl;
  renderLogoPreview();
  showToast('Branding saved');
}

// ── Logo helpers ─────────────────────────────────────────────────────────────
function renderLogoPreview() {
  const preview   = document.getElementById('logo-preview');
  const removeBtn = document.getElementById('logo-remove-btn');
  if (!preview) return;
  if (_logoUrl) {
    preview.innerHTML = `<img src="${_logoUrl}" style="width:100%;height:100%;object-fit:cover;display:block" />`;
    if (removeBtn) removeBtn.classList.remove('hidden');
  } else {
    preview.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="rgba(28,25,23,0.3)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';
    if (removeBtn) removeBtn.classList.add('hidden');
  }
}

function onLogoSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  e.target.value = '';
  if (file.size > 2 * 1024 * 1024) { showToast('Logo must be under 2 MB'); return; }
  if (file.type !== 'image/jpeg' && file.type !== 'image/png') { showToast('Only JPEG or PNG allowed'); return; }
  _logoFile = file;
  _logoUrl  = URL.createObjectURL(file);
  renderLogoPreview();
  showToast('Logo selected — tap Save to apply');
}

function removeLogo() {
  _logoFile          = null;
  _logoUrl           = null;
  _branding.logo_url = null;
  renderLogoPreview();
}

function addWallpaper() {
  if (_wallpapers.length >= 5) { showToast('Maximum 5 backgrounds'); return; }
  document.getElementById('wallpaper-input').click();
}

async function onWallpaperSelected(e) {
  const file = e.target.files[0];
  if (!file) return;
  e.target.value = '';
  if (file.size > 5 * 1024 * 1024) { showToast('File must be under 5 MB'); return; }
  const isImage = file.type === 'image/jpeg' || file.type === 'image/png';
  const isVideo = file.type === 'video/mp4';
  if (!isImage && !isVideo) { showToast('Only JPEG, PNG or MP4 allowed'); return; }
  const ext  = isImage ? (file.type === 'image/jpeg' ? 'jpg' : 'png') : 'mp4';
  // Path must start with userId/ to satisfy storage RLS policy
  const path = currentUser.id + '/branding/wp_' + Date.now() + '.' + ext;
  showToast('Uploading background…', true);
  try {
    const { error } = await _sb.storage.from(BUCKET).upload(path, file, { contentType: file.type });
    if (error) { showToast('Upload failed: ' + error.message); return; }
    const { data } = _sb.storage.from(BUCKET).getPublicUrl(path);
    const publicUrl = data?.publicUrl;
    if (!publicUrl) { showToast('Upload failed: could not get URL'); return; }
    _wallpapers.push({ url: publicUrl, type: isImage ? 'image' : 'video' });
    renderWallpaperSlots();
    showToast('Background added — tap Save to apply');
  } catch (err) {
    showToast('Upload failed: ' + (err.message || err));
  }
}

function removeWallpaper(idx) {
  _wallpapers.splice(idx, 1);
  renderWallpaperSlots();
}

function renderWallpaperSlots() {
  const container = document.getElementById('wallpaper-slots');
  if (!container) return;
  document.getElementById('wallpaper-count').textContent = _wallpapers.length + ' / 5';
  container.innerHTML = '';
  _wallpapers.forEach((wp, i) => {
    const slot = document.createElement('div');
    slot.style.cssText = 'position:relative;aspect-ratio:1/1;border-radius:10px;overflow:hidden;background:#EAE4D9';
    if (wp.type === 'image') {
      const img = document.createElement('img');
      img.src = wp.url;
      img.style.cssText = 'width:100%;height:100%;object-fit:cover;display:block';
      slot.appendChild(img);
    } else {
      slot.style.background = '#1C1917';
      slot.innerHTML = '<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#F5F0E8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg></div>';
    }
    const x = document.createElement('button');
    x.style.cssText = 'position:absolute;top:3px;right:3px;width:18px;height:18px;border-radius:50%;background:rgba(28,25,23,0.75);color:#F5F0E8;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0';
    x.innerHTML = '<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    x.onclick = () => removeWallpaper(i);
    slot.appendChild(x);
    container.appendChild(slot);
  });
  if (_wallpapers.length < 5) {
    const add = document.createElement('div');
    add.onclick = addWallpaper;
    add.style.cssText = 'aspect-ratio:1/1;border-radius:10px;border:2px dashed rgba(28,25,23,0.18);cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .15s';
    add.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="rgba(28,25,23,0.3)" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
    add.onmouseover = () => { add.style.background = '#EAE4D9'; };
    add.onmouseout  = () => { add.style.background = 'transparent'; };
    container.appendChild(add);
  }
}
