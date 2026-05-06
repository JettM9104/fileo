// ── BRANDING SHARED — used by cloud.html and branding.html ──────────────────

const BUCKET = 'uploads';

// ── Profile list state ──────────────────────────────────────────────────────
let _profiles       = [];
let _editingId      = null;
let _profilesLoaded = false;

// ── Per-editor session state ────────────────────────────────────────────────
let _branding  = { brand_name:'', tagline:'', domain_url:'', accent_color:'#8B6F47', bg_color:'#F5F0E8', logo_url:null };
let _wallpapers = [];
let _logoUrl   = null;
let _logoFile  = null;

function isColorDark(hex) {
  try {
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    return (0.299*r + 0.587*g + 0.114*b) < 140;
  } catch { return false; }
}

function generateProfileId() {
  return 'p_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2,7);
}

function updateBrandPreview() {
  const bg = document.getElementById('brand-preview-bg');
  if (!bg) return;

  const name    = document.getElementById('brand-name')?.value.trim()    || 'Your Brand';
  const tagline = document.getElementById('brand-tagline')?.value.trim() || '';
  const domain  = document.getElementById('brand-domain')?.value.trim()  || '';
  const initial = name[0]?.toUpperCase() || 'F';

  const hasWall   = _wallpapers.length > 0;
  const firstWall = hasWall ? _wallpapers[0] : null;

  // ── Background ──
  if (hasWall && firstWall.type === 'image') {
    bg.style.backgroundImage    = `url('${firstWall.url}')`;
    bg.style.backgroundSize     = 'cover';
    bg.style.backgroundPosition = 'center';
    bg.style.backgroundColor    = '#000';
  } else if (hasWall && firstWall.type === 'video') {
    bg.style.backgroundImage = '';
    bg.style.backgroundColor = '#1C1917';
  } else {
    bg.style.backgroundImage = '';
    bg.style.backgroundColor = _branding.bg_color;
  }

  // ── Dim overlay ──
  const overlay = document.getElementById('preview-wall-overlay');
  if (overlay) overlay.style.display = hasWall ? '' : 'none';

  // ── Color scheme ──
  let text, sub, cardBg, footerColor, nameColor, taglineColor, domainColor;
  if (hasWall) {
    // Glass card over wallpaper — card is white/frosted, corners are white text
    text        = '#1C1917';
    sub         = 'rgba(28,25,23,0.45)';
    cardBg      = 'rgba(255,255,255,0.90)';
    footerColor = 'rgba(28,25,23,0.35)';
    nameColor   = '#fff';
    taglineColor= 'rgba(255,255,255,0.72)';
    domainColor = 'rgba(255,255,255,0.72)';
  } else {
    const isDark = isColorDark(_branding.bg_color);
    text        = isDark ? '#F5F0E8'                  : '#1C1917';
    sub         = isDark ? 'rgba(245,240,232,0.45)'   : 'rgba(28,25,23,0.4)';
    cardBg      = isDark ? 'rgba(245,240,232,0.08)'   : 'rgba(28,25,23,0.05)';
    footerColor = isDark ? 'rgba(245,240,232,0.25)'   : 'rgba(28,25,23,0.3)';
    nameColor   = text;
    taglineColor= sub;
    domainColor = sub;
  }

  // ── Card ──
  const card = document.getElementById('preview-card');
  if (card) {
    card.style.background    = cardBg;
    card.style.backdropFilter = hasWall ? 'blur(24px)' : '';
    card.style.webkitBackdropFilter = hasWall ? 'blur(24px)' : '';
    card.style.boxShadow     = hasWall ? '0 8px 40px rgba(0,0,0,0.22)' : '';
  }

  // ── Label ──
  const labelEl = document.getElementById('preview-ready-label');
  if (labelEl) labelEl.style.color = sub;

  // ── Card content ──
  document.getElementById('preview-card-text').style.color  = text;
  document.getElementById('preview-card-meta').style.color  = sub;
  document.getElementById('preview-btn-mock').style.background = _branding.accent_color;
  document.getElementById('preview-footer').style.color     = footerColor;

  // ── Brand corner ──
  document.getElementById('preview-name').textContent = name;
  document.getElementById('preview-name').style.color = nameColor;

  const tagEl = document.getElementById('preview-tagline');
  if (tagEl) { tagEl.textContent = tagline; tagEl.style.display = tagline ? '' : 'none'; tagEl.style.color = taglineColor; }

  const domEl = document.getElementById('preview-domain');
  if (domEl) { domEl.textContent = domain; domEl.style.display = domain ? '' : 'none'; domEl.style.color = domainColor; }

  // ── Logo ──
  const logoEl = document.getElementById('preview-logo');
  if (logoEl) {
    if (_logoUrl) {
      logoEl.innerHTML = `<img src="${_logoUrl}" style="width:100%;height:100%;object-fit:cover;display:block">`;
      logoEl.style.background = 'transparent';
    } else {
      logoEl.innerHTML = '';
      logoEl.textContent = initial;
      logoEl.style.background = _branding.accent_color;
    }
  }
}

// ── Profile list ─────────────────────────────────────────────────────────────
async function loadBranding() {
  if (_profilesLoaded) {
    if (_editingId !== null) _renderEditorForProfile(_editingId);
    else renderProfilesList();
    return;
  }
  const { data } = await _sb.from('user_branding').select('*').eq('user_id', currentUser.id).maybeSingle();
  if (data) {
    if (Array.isArray(data.profiles) && data.profiles.length > 0) {
      _profiles = data.profiles.map(p => ({
        ...p,
        wallpapers: (p.wallpapers || []).map(wp => typeof wp === 'string' ? { url: wp, type: 'image' } : wp),
      }));
    } else {
      _profiles = [{
        id:           generateProfileId(),
        name:         'Default',
        is_default:   true,
        brand_name:   data.brand_name   || '',
        tagline:      data.tagline       || '',
        domain_url:   data.domain_url    || '',
        accent_color: data.accent_color  || '#8B6F47',
        bg_color:     data.bg_color      || '#F5F0E8',
        logo_url:     data.logo_url      || null,
        wallpapers:   (data.wallpapers   || []).map(wp => typeof wp === 'string' ? { url: wp, type: 'image' } : wp),
      }];
    }
  }
  if (_profiles.length > 0 && !_profiles.some(p => p.is_default)) _profiles[0].is_default = true;
  _profilesLoaded = true;
  renderProfilesList();
}

function renderProfilesList() {
  const listView   = document.getElementById('profiles-list-view');
  const editorView = document.getElementById('profile-editor-view');
  if (!listView) return;
  listView.classList.remove('hidden');
  if (editorView) editorView.classList.add('hidden');

  const grid = document.getElementById('profiles-cards');
  if (!grid) return;
  grid.innerHTML = '';

  _profiles.forEach(p => {
    const card = document.createElement('div');
    card.style.cssText = 'border-radius:16px;overflow:hidden;border:1px solid rgba(28,25,23,0.10);background:#FDFAF5;cursor:pointer;transition:transform .15s,box-shadow .15s';
    card.onmouseover = () => { card.style.transform='translateY(-2px)'; card.style.boxShadow='0 6px 20px rgba(28,25,23,0.10)'; };
    card.onmouseout  = () => { card.style.transform=''; card.style.boxShadow=''; };

    // Colored strip
    const strip = document.createElement('div');
    strip.style.cssText = `height:80px;background:${p.bg_color || '#F5F0E8'};display:flex;align-items:center;justify-content:center`;
    if (p.logo_url) {
      strip.innerHTML = `<img src="${p.logo_url}" style="width:48px;height:48px;border-radius:12px;object-fit:cover;box-shadow:0 2px 8px rgba(0,0,0,0.15)">`;
    } else {
      const initial = (p.brand_name || p.name || '?')[0].toUpperCase();
      strip.innerHTML = `<div style="width:48px;height:48px;border-radius:12px;background:${p.accent_color||'#8B6F47'};color:#F5F0E8;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:20px;box-shadow:0 2px 8px rgba(0,0,0,0.12)">${initial}</div>`;
    }

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:10px 12px';

    const nameSpan = document.createElement('span');
    nameSpan.style.cssText = 'flex:1;font-size:13px;font-weight:600;color:#1C1917;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
    nameSpan.textContent = p.name || 'Untitled';

    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;align-items:center;gap:4px;flex-shrink:0';

    if (p.is_default) {
      const badge = document.createElement('span');
      badge.style.cssText = 'font-size:10px;font-weight:700;padding:2px 7px;border-radius:99px;background:#8B6F47;color:#F5F0E8';
      badge.textContent = 'Default';
      actions.appendChild(badge);
    }

    const editBtn = document.createElement('button');
    editBtn.title = 'Edit';
    editBtn.style.cssText = 'width:28px;height:28px;border-radius:8px;background:#EAE4D9;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:#1C1917';
    editBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
    editBtn.onclick = e => { e.stopPropagation(); openProfileEditor(p.id); };
    actions.appendChild(editBtn);

    if (_profiles.length > 1) {
      const delBtn = document.createElement('button');
      delBtn.title = 'Delete';
      delBtn.style.cssText = 'width:28px;height:28px;border-radius:8px;background:#EAE4D9;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;color:rgba(28,25,23,0.45)';
      delBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>`;
      delBtn.onclick = e => { e.stopPropagation(); deleteProfile(p.id); };
      actions.appendChild(delBtn);
    }

    row.appendChild(nameSpan);
    row.appendChild(actions);
    card.appendChild(strip);
    card.appendChild(row);
    card.onclick = () => openProfileEditor(p.id);
    grid.appendChild(card);
  });

  const addBtn = document.getElementById('add-profile-btn');
  if (addBtn) addBtn.style.display = _profiles.length >= 3 ? 'none' : '';
}

function addNewProfile() {
  if (_profiles.length >= 3) { showToast('Maximum 3 branding profiles'); return; }
  const p = {
    id: generateProfileId(), name: 'Profile ' + (_profiles.length + 1),
    is_default: _profiles.length === 0,
    brand_name:'', tagline:'', domain_url:'',
    accent_color:'#8B6F47', bg_color:'#F5F0E8',
    logo_url:null, wallpapers:[],
  };
  _profiles.push(p);
  openProfileEditor(p.id);
}

function openProfileEditor(id) {
  _editingId = id;
  _renderEditorForProfile(id);
}

function _renderEditorForProfile(id) {
  const listView   = document.getElementById('profiles-list-view');
  const editorView = document.getElementById('profile-editor-view');
  if (!editorView) return;
  if (listView) listView.classList.add('hidden');
  editorView.classList.remove('hidden');

  const p = _profiles.find(x => x.id === id);
  if (!p) return;

  const nameInput = document.getElementById('profile-name-input');
  if (nameInput) nameInput.value = p.name || '';

  const defCheck = document.getElementById('profile-is-default');
  if (defCheck) { defCheck.checked = !!p.is_default; defCheck.disabled = !!p.is_default; }

  _branding.accent_color = p.accent_color || '#8B6F47';
  _branding.bg_color     = p.bg_color     || '#F5F0E8';
  _branding.logo_url     = p.logo_url     || null;
  _wallpapers = (p.wallpapers || []).map(wp => typeof wp === 'string' ? { url: wp, type: 'image' } : wp);
  _logoUrl = _branding.logo_url;
  _logoFile = null;

  document.getElementById('brand-name').value    = p.brand_name  || '';
  document.getElementById('brand-tagline').value = p.tagline      || '';
  document.getElementById('brand-domain').value  = p.domain_url   || '';

  renderWallpaperSlots();
  renderLogoPreview();
  updateBrandPreview();
}

function closeProfileEditor() {
  _editingId = null;
  _logoFile  = null;
  renderProfilesList();
}

async function deleteProfile(id) {
  const p = _profiles.find(x => x.id === id);
  if (!p) return;
  if (_profiles.length <= 1) { showToast('You must keep at least one profile'); return; }
  if (!confirm('Delete "' + (p.name || 'this profile') + '"? This cannot be undone.')) return;
  _profiles = _profiles.filter(x => x.id !== id);
  if (p.is_default && _profiles.length > 0) _profiles[0].is_default = true;
  await _persistProfiles();
  renderProfilesList();
  showToast('Branding deleted');
}

async function saveBranding() {
  if (_editingId === null) return;
  const idx = _profiles.findIndex(x => x.id === _editingId);
  if (idx === -1) return;

  let savedLogoUrl = _branding.logo_url;
  if (_logoFile) {
    showToast('Uploading logo…', true);
    const ext  = _logoFile.type === 'image/jpeg' ? 'jpg' : 'png';
    const path = currentUser.id + '/branding/logo_' + _editingId + '.' + ext;
    const { error: upErr } = await _sb.storage.from(BUCKET).upload(path, _logoFile, { contentType: _logoFile.type, upsert: true });
    if (upErr) { showToast('Logo upload failed: ' + upErr.message); return; }
    const { data: { publicUrl } } = _sb.storage.from(BUCKET).getPublicUrl(path);
    savedLogoUrl = publicUrl + '?t=' + Date.now();
    _logoFile = null;
  }

  const nameInput = document.getElementById('profile-name-input');
  const defCheck  = document.getElementById('profile-is-default');
  const makeDefault = defCheck?.checked ?? _profiles[idx].is_default;

  const updated = {
    ..._profiles[idx],
    name:         nameInput?.value.trim() || _profiles[idx].name,
    brand_name:   document.getElementById('brand-name').value.trim(),
    tagline:      document.getElementById('brand-tagline').value.trim(),
    domain_url:   document.getElementById('brand-domain').value.trim(),
    accent_color: _branding.accent_color,
    bg_color:     _branding.bg_color,
    logo_url:     savedLogoUrl,
    wallpapers:   _wallpapers,
  };

  if (makeDefault) {
    _profiles.forEach(p => { p.is_default = false; });
    updated.is_default = true;
  }

  _profiles[idx] = updated;
  _branding.logo_url = savedLogoUrl;
  _logoUrl = savedLogoUrl;
  renderLogoPreview();

  const ok = await _persistProfiles();
  if (ok) showToast('Branding saved');
}

async function _persistProfiles() {
  const def = _profiles.find(p => p.is_default) || _profiles[0];
  const record = {
    user_id:      currentUser.id,
    profiles:     _profiles,
    brand_name:   def?.brand_name   || '',
    tagline:      def?.tagline       || '',
    domain_url:   def?.domain_url    || '',
    accent_color: def?.accent_color  || '#8B6F47',
    bg_color:     def?.bg_color      || '#F5F0E8',
    logo_url:     def?.logo_url      || null,
    wallpapers:   def?.wallpapers    || [],
    updated_at:   new Date().toISOString(),
  };
  const { data: existing } = await _sb.from('user_branding').select('user_id').eq('user_id', currentUser.id).maybeSingle();
  const { error } = existing
    ? await _sb.from('user_branding').update(record).eq('user_id', currentUser.id)
    : await _sb.from('user_branding').insert(record);
  if (error) { showToast('Could not save: ' + error.message); return false; }
  return true;
}

// ── Logo helpers ──────────────────────────────────────────────────────────────
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
  updateBrandPreview();
  showToast('Logo selected — tap Save to apply');
}

function removeLogo() {
  _logoFile = null; _logoUrl = null; _branding.logo_url = null;
  renderLogoPreview();
  updateBrandPreview();
}

// ── Wallpaper helpers ─────────────────────────────────────────────────────────
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
    updateBrandPreview();
    showToast('Background added — tap Save to apply');
  } catch (err) {
    showToast('Upload failed: ' + (err.message || err));
  }
}

function removeWallpaper(idx) {
  _wallpapers.splice(idx, 1);
  renderWallpaperSlots();
  updateBrandPreview();
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
