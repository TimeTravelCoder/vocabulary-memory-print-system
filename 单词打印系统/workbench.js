/* Vocabulary selection and learning tools. All personal data stays in this browser. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const key = value => String(value || '').normalize('NFKC').trim().toLowerCase().replace(/\s+/g, ' ');
  const read = (name, fallback) => { try { return JSON.parse(localStorage.getItem(name)) ?? fallback; } catch { return fallback; } };
  let storageAlerted = false;
  const write = (name, value) => {
    try { localStorage.setItem(name, JSON.stringify(value)); storageAlerted = false; return true; }
    catch { if (!storageAlerted) alert('浏览器存储空间不足，请导出备份后清理。'); storageAlerted = true; return false; }
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const isRecord = value => value && typeof value === 'object' && !Array.isArray(value);
  const record = value => Object.assign(Object.create(null), isRecord(value) ? value : {});
  function normalizeReview(value) {
    const output = Object.create(null);
    for (const [storedKey, item] of Object.entries(isRecord(value) ? value : {}).slice(0, 20000)) {
      if (!isRecord(item) || !isRecord(item.word) || typeof item.word['单词'] !== 'string') continue;
      const normalized = key(item.word['单词']);
      const due = Number(item.due), stage = Number(item.stage);
      if (!normalized || normalized !== storedKey || !Number.isFinite(due) || !Number.isInteger(stage) || stage < 0) continue;
      const advanced = window.VocabAdvanced?.normalizeReviewItem?.(item) || item;
      output[normalized] = {
        word:item.word, due, stage:Math.min(stage, 100000),
        mistakes:Math.max(0, Math.min(100000, Number(advanced.mistakes) || 0)),
        successes:Math.max(0, Math.min(100000, Number(advanced.successes) || 0)),
        lastReviewed:Number.isFinite(Number(advanced.lastReviewed)) ? Number(advanced.lastReviewed) : 0
      };
    }
    return output;
  }
  function normalizePresets(value) {
    const output = Object.create(null);
    for (const [name, preset] of Object.entries(isRecord(value) ? value : {}).slice(0, 200)) {
      const cleanName = String(name).trim().slice(0, 60);
      if (!cleanName || !isRecord(preset)) continue;
      output[cleanName] = {controls:record(preset.controls), settings:record(preset.settings)};
    }
    return output;
  }
  let callbacks, excluded = new Set(), page = 0;
  let review = normalizeReview(read('vocab_review_v1', {}));
  let presets = normalizePresets(read('vocab_presets_v1', {}));
  let lastPresetChange = null;
  let refreshTimer = null;
  const settingsIds = [
    'minLetters','keepPhrases','deduplicate','familiarWords','definitionLanguage','definitionDetail','zhDefinitionCount',
    'printDuplex','printInkSaver','printDecorations','reviewOnly','reviewDueOnly','smartDensity','overflowStrategy',
    'exerciseMode','exampleMode','difficultyFilter','showMorphology','reviewStartDate','reviewIntervals','weakCopyBoost',
    'reviewPacketScope','weakWordBoost','bindingMode','calibrationScale','calibrationOffsetX','calibrationOffsetY',
    'bookletMode','customHeader','customFooter','studentName','className','planStartDate','planDeadline','dailyWordTarget',
    'printCopies','paperPrice','inkPrice','showPronunciationQr','qrProvider','multiBookMode','batchExportFormat',
    'optWordSlot','optPhoneticSlot','optZhDefinitionSlot','optEnDefinitionSlot'
  ];
  const radioSettings = ['enDefCount'];
  function settings() {
    const values = Object.fromEntries(settingsIds.filter(id => $(id)).map(id => [id, $(id).type === 'checkbox' ? $(id).checked : $(id).value]));
    for (const name of radioSettings) {
      const selected = document.querySelector(`input[name="${name}"]:checked`);
      if (selected) values[name] = selected.value;
    }
    return values;
  }
  function setValue(el, value) {
    if (!el) return;
    if (el.type === 'checkbox') {
      if (typeof value === 'boolean') el.checked = value;
      return;
    }
    if (el.type === 'number') {
      const numeric = Number(value);
      if (!Number.isFinite(numeric)) return;
      const min = el.min === '' ? numeric : Number(el.min);
      const max = el.max === '' ? numeric : Number(el.max);
      el.value = String(Math.min(max, Math.max(min, numeric)));
      return;
    }
    if (el.tagName === 'SELECT' && !Array.from(el.options).some(option => option.value === String(value))) return;
    if (typeof value === 'string' || typeof value === 'number') el.value = String(value);
  }
  function restore(values) {
    if (!isRecord(values)) return;
    for (const id of settingsIds) if (Object.hasOwn(values, id)) setValue($(id), values[id]);
    for (const name of radioSettings) {
      if (!Object.hasOwn(values, name)) continue;
      const radios = Array.from(document.querySelectorAll(`input[name="${name}"]`));
      if (radios.some(el => el.value === String(values[name]))) {
        radios.forEach(el => { el.checked = el.value === String(values[name]); });
      }
    }
  }
  function familiarSet() { return new Set($('familiarWords').value.split(/[\n,，;；]+/).map(key).filter(Boolean)); }
  function process(words, ignoreSelection = false) {
    const min = Math.max(0, Math.min(40, Number($('minLetters').value) || 0));
    const familiar = familiarSet(), seen = new Set();
    const now = Date.now();
    return words.filter(w => {
      const normalized = key(w['单词']);
      if (!normalized) return false;
      const phrase = /\s/.test(normalized);
      const latinLetters = normalized.match(/\p{Script=Latin}/gu)?.length || 0;
      if (!($('keepPhrases').checked && phrase) && latinLetters < min) return false;
      if (familiar.has(normalized) || (!ignoreSelection && excluded.has(normalized))) return false;
      if ($('reviewOnly').checked && !review[normalized]) return false;
      if ($('reviewDueOnly').checked && (!review[normalized] || Number(review[normalized].due) > now)) return false;
      const difficulty = $('difficultyFilter')?.value || 'all';
      if (difficulty !== 'all' && window.VocabAdvanced?.classifyDifficulty?.(w) !== difficulty) return false;
      const multiMode = $('multiBookMode')?.value || 'union';
      const sourceCount = Array.isArray(w._sources) ? w._sources.length : 1;
      const sourceTotal = Math.max(1, Number(w._sourceTotal) || 1);
      if (multiMode === 'shared' && sourceCount < 2) return false;
      if (multiMode === 'intersection' && sourceCount < sourceTotal) return false;
      if (multiMode === 'unique' && sourceCount !== 1) return false;
      if ($('deduplicate').checked && seen.has(normalized)) return false;
      seen.add(normalized);
      return true;
    });
  }
  function refresh() {
    clearTimeout(refreshTimer);
    write('vocab_workbench_settings_v1', settings());
    page = 0;
    callbacks.refresh();
    updateStats();
    if ($('wordManager').open) renderWords();
  }
  function queueRefresh() {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(refresh, 180);
  }
  function updateStats() {
    const all = callbacks.words(), filtered = process(all);
    $('filterStats').textContent = `原始 ${all.length} 词 → 打印 ${filtered.length} 词（已排除 ${all.length - filtered.length} 词）`;
    const entries = Object.values(review).filter(item => isRecord(item) && Number.isFinite(Number(item.due)));
    $('reviewStats').textContent = `错词收藏 ${entries.length} 个 · 今日待复习 ${entries.filter(r => r.due <= Date.now()).length} 个`;
  }
  function rows() {
    const query = key($('wordSearch').value);
    return process(callbacks.words(), true).filter(w => !query || key(w['单词']).includes(query) || String(w['释义(中文)'] || '').includes(query));
  }
  function renderWords() {
    const all = rows();
    const count = Math.max(1, Math.ceil(all.length / 80));
    page = Math.max(0, Math.min(page, count - 1));
    $('wordManagerCount').textContent = `共 ${all.length} 词 · 第 ${page + 1}/${count} 页（每页80词）`;
    $('wordRows').innerHTML = all.slice(page * 80, (page + 1) * 80).map(w => {
      const k = key(w['单词']), saved = review[k];
      return `<tr><td><input type="checkbox" data-select-word="${escape(k)}" aria-label="打印 ${escape(w['单词'])}" ${excluded.has(k) ? '' : 'checked'}></td><td><strong>${escape(w['单词'])}</strong><small>${escape(w['释义(中文)'] || '')}</small></td><td><button type="button" data-review-word="${escape(k)}">${saved ? '移出错词' : '加入错词'}</button>${saved ? `<button type="button" data-review-correct="${escape(k)}">答对</button><button type="button" data-review-wrong="${escape(k)}">答错</button><small>错 ${saved.mistakes || 0} 次 · 下次：${escape(new Date(saved.due).toLocaleDateString())}</small>` : ''}</td></tr>`;
    }).join('') || '<tr><td colspan="3">没有符合条件的单词，请调整筛选。</td></tr>';
    $('wordPrev').disabled = page === 0;
    $('wordNext').disabled = page >= count - 1;
  }
  function toggleReview(k) {
    if (review[k]) delete review[k];
    else {
      const word = callbacks.words().find(w => key(w['单词']) === k);
      if (word) review[k] = { word, stage: 0, due: Date.now(), mistakes:0, successes:0, lastReviewed:0 };
    }
    write('vocab_review_v1', review);
    refresh();
  }
  function downloadJson(value, name) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function isPresetControl(el) {
    const hasIdentity = Boolean(el?.id || (el?.type === 'radio' && el?.name));
    return Boolean(hasIdentity && el.closest('.sidebar') && el.type !== 'file' &&
      !['categorySelect','bookSelect','presetSelect','presetName'].includes(el.id));
  }
  function snapshot() {
    const controls = {};
    document.querySelectorAll('.sidebar input, .sidebar select').forEach(el => {
      if (!isPresetControl(el)) return;
      if (el.type === 'radio') { if (el.checked) controls[`radio:${el.name}`] = el.value; }
      else if (el.id) controls[el.id] = el.type === 'checkbox' ? el.checked : el.value;
    });
    return {controls, settings:settings()};
  }
  function renderPresets() {
    const previous = $('presetSelect').value;
    $('presetSelect').innerHTML = '<option value="">选择已保存方案</option>' + Object.keys(presets).map(n => `<option value="${escape(n)}">${escape(n)}</option>`).join('');
    if (Object.hasOwn(presets, previous)) $('presetSelect').value = previous;
  }
  function updateCopyPresetActive() {
    const word = $('optWordSlot')?.checked;
    const phonetic = $('optPhoneticSlot')?.checked;
    const zh = $('optZhDefinitionSlot')?.checked;
    const en = $('optEnDefinitionSlot')?.checked;
    document.querySelectorAll('.copy-preset-btn').forEach(btn => {
      const p = btn.dataset.copyPreset;
      let active = false;
      if (p === 'all') active = word && phonetic && zh && en;
      else if (p === 'common') active = word && phonetic && zh && !en;
      else if (p === 'word_def') active = word && !phonetic && zh && !en;
      else if (p === 'word_only') active = word && !phonetic && !zh && !en;
      else if (p === 'none') active = !word && !phonetic && !zh && !en;
      btn.classList.toggle('active', Boolean(active));
    });
  }
  function applyCopyPreset(preset) {
    const word = $('optWordSlot'), phonetic = $('optPhoneticSlot'), zh = $('optZhDefinitionSlot'), en = $('optEnDefinitionSlot');
    if (!word || !phonetic || !zh || !en) return;
    if (preset === 'all') { word.checked = true; phonetic.checked = true; zh.checked = true; en.checked = true; }
    else if (preset === 'common') { word.checked = true; phonetic.checked = true; zh.checked = true; en.checked = false; }
    else if (preset === 'word_def') { word.checked = true; phonetic.checked = false; zh.checked = true; en.checked = false; }
    else if (preset === 'word_only') { word.checked = true; phonetic.checked = false; zh.checked = false; en.checked = false; }
    else if (preset === 'none') { word.checked = false; phonetic.checked = false; zh.checked = false; en.checked = false; }
    en.dispatchEvent(new Event('change'));
    updateCopyPresetActive();
  }
  function applyPreset(preset) {
    if (!isRecord(preset)) return;
    const controls = isRecord(preset.controls) ? preset.controls : {};
    const presetSettings = isRecord(preset.settings) ? preset.settings : {};
    const legacyCopyDefaults = {optWordSlot:true,optPhoneticSlot:true,optZhDefinitionSlot:false,optEnDefinitionSlot:true};
    for (const [id, value] of Object.entries(legacyCopyDefaults)) {
      if (!Object.hasOwn(controls, id) && !Object.hasOwn(presetSettings, id)) setValue($(id), value);
    }
    restore(presetSettings);
    for (const [id, value] of Object.entries(controls)) {
      if (id.startsWith('radio:')) {
        const radioName = id.slice(6);
        const radios = Array.from(document.querySelectorAll('.sidebar input[type="radio"]')).filter(el => el.name === radioName);
        if (radios.some(el => el.value === String(value))) {
          radios.forEach(el => { el.checked = el.value === String(value); });
          const preferenceKeys = {
            paperTheme:'vocab_print_theme',
            fontSizeMode:'vocab_print_fontsize',
            cardStyle:'vocab_print_cardstyle',
            marginMode:'vocab_print_margin'
          };
          if (preferenceKeys[radioName]) {
            try { localStorage.setItem(preferenceKeys[radioName], String(value)); } catch {}
          }
        }
      } else {
        const el = $(id); if (!isPresetControl(el)) continue;
        setValue(el, value);
      }
    }
    updateCopyPresetActive();
    callbacks.applyControls();
    refresh();
  }
  function validateWords(data) {
    if (!Array.isArray(data) || data.some(w => !w || typeof w !== 'object' || typeof w['单词'] !== 'string' || !w['单词'].trim())) throw new Error('词书必须是数组，每条记录必须包含非空的“单词”字段。');
    return data;
  }
  async function mergeFiles(files) {
    const selected = Array.from(files || []);
    if (!selected.length) return;
    if (selected.length > 50 || selected.reduce((sum, file) => sum + file.size, 0) > 100 * 1024 * 1024) {
      throw new Error('一次最多合并50个文件，且总大小不能超过100MB');
    }
    const baseWords = callbacks.words();
    const batches = await Promise.all(selected.map(async file => validateWords(JSON.parse(await file.text()))));
    if (callbacks.words() !== baseWords) throw new Error('读取期间当前词书已切换，请重新选择要合并的文件');
    const books = [{name:'当前词书', words:baseWords}, ...batches.map((words, index) => ({name:selected[index].name || `本地词书${index + 1}`, words}))];
    const words = window.VocabAdvanced?.mergeWordbooks?.(books, 'union') || baseWords.concat(...batches);
    callbacks.replace(words, `合并词书（${words.length}条）`);
    refresh();
  }
  function init(cb) {
    callbacks = cb;
    restore(read('vocab_workbench_settings_v1', {}));
    for (const id of settingsIds) {
      const el = $(id);
      if (!el) continue;
      const liveInput = el.tagName === 'TEXTAREA' || el.type === 'number';
      el.addEventListener(liveInput ? 'input' : 'change', liveInput ? queueRefresh : refresh);
    }
    for (const name of radioSettings) {
      document.querySelectorAll(`input[name="${name}"]`).forEach(el => el.addEventListener('change', refresh));
    }
    document.querySelectorAll('.copy-preset-btn').forEach(btn => {
      btn.onclick = () => applyCopyPreset(btn.dataset.copyPreset);
    });
    ['optWordSlot', 'optPhoneticSlot', 'optZhDefinitionSlot', 'optEnDefinitionSlot'].forEach(id => {
      const el = $(id);
      if (el) el.addEventListener('change', updateCopyPresetActive);
    });
    updateCopyPresetActive();
    $('manageWords').onclick = () => { page = 0; renderWords(); $('wordManager').showModal(); };
    $('closeWordManager').onclick = () => $('wordManager').close();
    $('wordSearch').oninput = () => { page = 0; renderWords(); };
    $('wordPrev').onclick = () => { page--; renderWords(); };
    $('wordNext').onclick = () => { page++; renderWords(); };
    $('wordRows').onchange = event => {
      const k = event.target.dataset.selectWord; if (!k) return;
      if (event.target.checked) excluded.delete(k); else excluded.add(k);
      callbacks.refresh(); updateStats();
    };
    $('wordRows').onclick = event => {
      const k = event.target.dataset.reviewWord;
      if (k) toggleReview(k);
      const correct = event.target.dataset.reviewCorrect;
      const wrong = event.target.dataset.reviewWrong;
      const target = correct || wrong;
      if (target && review[target]) {
        const intervals = window.VocabAdvanced?.parseIntervals?.($('reviewIntervals')?.value) || [1,2,4,7,15,30];
        const updated = window.VocabAdvanced?.advanceReview?.(review[target], Boolean(correct), Date.now(), intervals);
        review[target] = updated ? {...updated, word:review[target].word} : review[target];
        write('vocab_review_v1', review); refresh();
      }
    };
    $('selectMatching').onclick = () => { rows().forEach(w => excluded.delete(key(w['单词']))); callbacks.refresh(); updateStats(); renderWords(); };
    $('excludeMatching').onclick = () => { rows().forEach(w => excluded.add(key(w['单词']))); callbacks.refresh(); updateStats(); renderWords(); };
    $('restoreSelection').onclick = () => { excluded.clear(); refresh(); };
    $('openReview').onclick = () => {
      const words = Object.values(review).map(r => r.word);
      if (!words.length) return alert('请先在“自选单词与错词”中收藏单词。');
      callbacks.replace(words, '我的错词复习本'); refresh();
    };
    $('exportReview').onclick = () => downloadJson(Object.values(review).map(r => r.word), '错词复习清单.json');
    $('mergeLocal').onclick = () => $('mergeFileInput').click();
    $('mergeFileInput').onchange = async event => {
      try { await mergeFiles(event.target.files); } catch(error) { alert('合并失败：' + error.message); }
      event.target.value = '';
    };
    $('mergeRemote').onclick = async () => {
      const path = $('mergeBookSelect').value;
      if (!path) return alert('请选择要合并的词书。');
      const baseWords = callbacks.words();
      $('mergeRemote').disabled = true;
      try {
        const res = await fetch(`/api/book?path=${encodeURIComponent(path)}`);
        if (!res.ok) throw new Error('无法读取词书');
        const added = validateWords(await res.json());
        if (callbacks.words() !== baseWords) throw new Error('下载期间当前词书已切换，请重新执行合并');
        const sourceName = $('mergeBookSelect').selectedOptions?.[0]?.textContent || path;
        const words = window.VocabAdvanced?.mergeWordbooks?.([
          {name:'当前词书', words:baseWords}, {name:sourceName, words:added}
        ], 'union') || baseWords.concat(added);
        callbacks.replace(words, `合并词书（${words.length}条）`); refresh();
      } catch(error) { alert('合并失败：' + error.message); }
      finally { $('mergeRemote').disabled = false; }
    };
    $('savePreset').onclick = () => {
      const name = $('presetName').value.trim();
      if (!name) return alert('请输入方案名称。');
      lastPresetChange = {name, previous:presets[name]};
      $('undoPreset').hidden = false;
      presets[name] = snapshot(); write('vocab_presets_v1', presets); renderPresets(); $('presetSelect').value = name;
    };
    $('applyPreset').onclick = () => { const p = presets[$('presetSelect').value]; if (p) applyPreset(p); };
    $('deletePreset').onclick = () => {
      const name = $('presetSelect').value; if (!name) return;
      lastPresetChange = {name, previous:presets[name]}; $('undoPreset').hidden = false;
      delete presets[name]; write('vocab_presets_v1', presets); renderPresets();
    };
    $('undoPreset').onclick = () => {
      if (!lastPresetChange) return;
      const {name, previous} = lastPresetChange;
      if (previous === undefined) delete presets[name]; else presets[name] = previous;
      lastPresetChange = null; $('undoPreset').hidden = true;
      write('vocab_presets_v1', presets); renderPresets();
    };
    $('backupLearning').onclick = () => downloadJson({version:1,review,presets,settings:settings()}, '单词学习与方案备份.json');
    $('restoreLearning').onclick = () => $('learningFileInput').click();
    $('learningFileInput').onchange = async event => {
      const file = event.target.files?.[0];
      if (!file) return;
      try {
        if (file.size > 50 * 1024 * 1024) throw new Error('备份文件不能超过50MB');
        const data = JSON.parse(await file.text());
        if (!isRecord(data) || data.version !== 1 || !isRecord(data.review) || !isRecord(data.presets)) throw new Error('备份格式不正确');
        const importedReview = normalizeReview(data.review);
        if (Object.keys(importedReview).length !== Object.keys(data.review).length) throw new Error('错词记录不正确');
        const importedPresets = normalizePresets(data.presets);
        if (Object.keys(importedPresets).length !== Object.keys(data.presets).length) throw new Error('排版方案记录不正确');
        review = Object.assign(Object.create(null), review, importedReview);
        presets = Object.assign(Object.create(null), presets, importedPresets);
        write('vocab_review_v1', review); write('vocab_presets_v1', presets);
        restore(data.settings || {}); renderPresets(); refresh();
      } catch(error) { alert('恢复失败：' + error.message); }
      event.target.value = '';
    };
    renderPresets(); updateStats(); callbacks.refresh();
  }
  function populateCatalog(catalog) {
    $('mergeBookSelect').innerHTML = '<option value="">选择第二本内置词书</option>' + Object.entries(catalog).flatMap(([category,books]) => books.map(b => `<option value="${escape(b.path)}">${escape(category + ' / ' + b.name)}</option>`)).join('');
    if ($('batchBookSelect')) $('batchBookSelect').innerHTML = Object.entries(catalog).flatMap(([category,books]) => books.map(b => `<option value="${escape(b.path)}">${escape(category + ' / ' + b.name)} (${Number(b.count) || 0}词)</option>`)).join('');
  }
  function bookChanged() { excluded.clear(); if (callbacks) updateStats(); }
  function options() { return settings(); }
  function reviewInfo(wordOrKey) { return review[key(isRecord(wordOrKey) ? wordOrKey['单词'] : wordOrKey)] || null; }
  function reviewWords() { return Object.values(review).map(item => item.word); }
  function reviewSnapshot() { return typeof structuredClone === 'function' ? structuredClone(review) : JSON.parse(JSON.stringify(review)); }
  function preflight(words, config) {
    const warnings = [];
    if (!words.length) warnings.push('没有可打印的单词，请放宽筛选或恢复勾选。');
    const longWords = words.filter(w => String(w['单词']).length > 24);
    if (longWords.length) warnings.push(`${longWords.length} 个长单词或短语可能被截短，例如 ${longWords.slice(0,3).map(w=>w['单词']).join('、')}。`);
    if (config.definitionDetail === 'full' && config.wordsPerPage > 6) warnings.push('完整释义建议每页4～6词；可在“释义显示”中应用精读推荐。');
    const longDefs = words.filter(w => String(w['释义(中文)'] || '').length > 65 || String(w['释义(英文)'] || '').length > 200);
    if (longDefs.length) warnings.push(config.definitionDetail === 'full'
      ? `${longDefs.length} 个词包含长释义，已启用完整显示与自动分页；异常超长的单条释义请检查打印续页。`
      : `${longDefs.length} 个词的释义较长；精简模式可能截短，可切换完整释义。`);
    const hasCopyPractice = config.showWordSlot !== false || config.showPhoneticSlot !== false || config.showZhDefinitionSlot === true || config.showEnDefinitionSlot !== false;
    if (config.wordsPerPage >= 13 && hasCopyPractice) warnings.push('高密度模式书写空间较小，长释义精简显示。');
    const pageCount = Math.ceil(words.length / config.wordsPerPage) + (config.showCover ? 1 : 0);
    const sheets = config.printDuplex === 'off' ? pageCount : Math.ceil(pageCount / 2);
    return {warnings,pageCount,sheets};
  }
  async function exportFile(payload, kind, signal, onProgress) {
    const id = crypto.randomUUID().replaceAll('-', '');
    let jobCreated = false, cancelSent = false;
    const cancel = () => {
      if (!jobCreated || cancelSent) return;
      cancelSent = true;
      fetch('/api/export-jobs/' + id + '/cancel', {
        method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'
      }).catch(()=>{});
    };
    signal.addEventListener('abort', cancel, {once:true});
    try {
      signal.throwIfAborted();
      const response = await fetch('/api/export-jobs', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,id,kind})});
      const started = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(started.error || '无法启动导出');
      jobCreated = true;
      signal.throwIfAborted();
      while (true) {
        signal.throwIfAborted();
        const res = await fetch('/api/export-jobs/' + id, {signal});
        if (!res.ok) throw new Error('读取任务进度失败');
        const job = await res.json(); if (onProgress) onProgress(job);
        if (job.state === 'done') {
          const file = await fetch('/api/export-jobs/' + id + '/file', {signal});
          if (!file.ok) throw new Error('下载文件失败');
          return file;
        }
        if (job.state === 'error') throw new Error(job.error);
        if (job.state === 'cancelled') throw new DOMException('已取消', 'AbortError');
        await new Promise((resolve, reject) => {
          const onAbort = () => {
            clearTimeout(timer); reject(new DOMException('已取消', 'AbortError'));
          };
          const timer = setTimeout(() => {
            signal.removeEventListener('abort', onAbort); resolve();
          }, 500);
          signal.addEventListener('abort', onAbort, {once:true});
        });
      }
    } finally {
      if (signal.aborted) cancel();
      signal.removeEventListener('abort', cancel);
    }
  }
  window.VocabWorkbench = {init,process,options,bookChanged,populateCatalog,updateStats,validateWords,preflight,exportFile,key,reviewInfo,reviewWords,reviewSnapshot,applyCopyPreset,updateCopyPresetActive};
})();
