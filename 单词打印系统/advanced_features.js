/* Optional advanced learning, layout and export helpers. Pure functions stay testable. */
(() => {
  'use strict';

  const DAY = 86400000;
  const DEFAULT_INTERVALS = Object.freeze([1, 2, 4, 7, 15, 30]);
  const clamp = (value, min, max) => Math.min(max, Math.max(min, Number(value) || 0));
  const key = value => String(value || '').normalize('NFKC').trim().toLowerCase().replace(/\s+/g, ' ');
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[character]));

  function hashSeed(value) {
    let hash = 2166136261;
    for (const character of String(value ?? '')) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
    return hash >>> 0;
  }

  function seededRandom(seed) {
    let state = typeof seed === 'number' ? seed >>> 0 : hashSeed(seed);
    return () => {
      state += 0x6D2B79F5;
      let value = state;
      value = Math.imul(value ^ value >>> 15, value | 1);
      value ^= value + Math.imul(value ^ value >>> 7, value | 61);
      return ((value ^ value >>> 14) >>> 0) / 4294967296;
    };
  }

  function seededShuffle(items, seed = 'vocabulary') {
    const output = Array.from(items || []);
    const random = seededRandom(seed);
    for (let index = output.length - 1; index > 0; index--) {
      const target = Math.floor(random() * (index + 1));
      [output[index], output[target]] = [output[target], output[index]];
    }
    return output;
  }

  function latinLength(value) {
    return String(value || '').match(/\p{Script=Latin}/gu)?.length || 0;
  }

  function difficultyScore(word) {
    const spelling = String(word?.['单词'] || '');
    const english = String(word?.['释义(英文)'] || '');
    const chinese = String(word?.['释义(中文)'] || '');
    const letters = latinLength(spelling);
    let score = letters * 0.55 + Math.min(6, english.length / 55) + Math.min(3, chinese.length / 35);
    if (/[-'’]/.test(spelling)) score += 1;
    if (/\s/.test(spelling.trim())) score += 2;
    if (letters >= 14) score += 2;
    if (/[^\x00-\x7f]/.test(spelling)) score += 0.5;
    return Math.round(score * 10) / 10;
  }

  function classifyDifficulty(word) {
    const score = difficultyScore(word);
    if (score < 6.5) return 'basic';
    if (score < 11.5) return 'intermediate';
    return 'advanced';
  }

  function englishDefinitions(value, maximum = 99) {
    const raw = String(value ?? '').replace(/\r\n?/g, '\n').trim();
    if (!raw || raw === '—' || raw.toLowerCase() === 'none') return [];
    const limit = Math.max(1, Number(maximum) || 1);
    return raw
      .split(/\n+|(?=\(\d+\)\s*)/)
      .map(item => item.trim().replace(/^\(\d+\)\s*/, ''))
      .filter(Boolean)
      .slice(0, limit);
  }

  function wordWeight(word, config = {}) {
    const spelling = String(word?.['单词'] || '');
    const zh = String(word?.['释义(中文)'] || '');
    const en = String(word?.['释义(英文)'] || '');
    const example = String(word?.['例句'] || word?.['英文例句'] || word?.example || '');
    let weight = 1;
    weight += Math.max(0, latinLength(spelling) - 10) / 18;
    weight += Math.min(1.4, zh.length / (config.definitionDetail === 'full' ? 100 : 180));
    weight += Math.min(2.2, en.length / (config.definitionDetail === 'full' ? 170 : 360));
    if (config.exampleMode && config.exampleMode !== 'off') weight += Math.min(0.8, example.length / 180);
    if (config.showMorphology) weight += 0.18;
    if (config.showPronunciationQr) weight += 0.2;
    const copyFieldCount = [
      config.showWordSlot !== false,
      config.showPhoneticSlot !== false,
      config.showZhDefinitionSlot === true,
      config.showEnDefinitionSlot !== false
    ].filter(Boolean).length;
    weight += (copyFieldCount - 3) * 0.08;
    return clamp(weight, 0.8, 4);
  }

  function smartPageGroups(words, config = {}) {
    const maximum = clamp(config.wordsPerPage || 10, 2, 20);
    if (!Array.isArray(words) || !words.length) return [];
    const budget = maximum * (config.definitionDetail === 'full' ? 0.92 : 1);
    const groups = [];
    let current = [], used = 0;
    for (const word of words) {
      const weight = wordWeight(word, config);
      if (current.length && (current.length >= maximum || used + weight > budget)) {
        groups.push(current); current = []; used = 0;
      }
      current.push(word); used += weight;
    }
    if (current.length) groups.push(current);
    return groups;
  }

  function overflowRecommendation(words, config = {}) {
    const list = Array.isArray(words) ? words : [];
    const base = clamp(config.wordsPerPage || 10, 4, 16);
    const average = list.length ? list.reduce((sum, word) => sum + wordWeight(word, config), 0) / list.length : 1;
    const recommended = clamp(Math.floor(base / Math.max(1, average * 0.82)), 4, base);
    const severe = average > 1.9 || list.some(word => wordWeight(word, config) >= 3.2);
    return {
      wordsPerPage: recommended,
      fontSizeMode: severe ? 'small' : (config.fontSizeMode || 'medium'),
      definitionDetail: severe && config.overflowStrategy === 'brief' ? 'brief' : (config.definitionDetail || 'brief'),
      smartDensity: true,
      reason: severe ? '检测到超长单词或释义，已降低密度并缩小字号。' : '已根据内容长度自动调整每页容量。'
    };
  }

  function firstLetterMask(value) {
    return String(value || '').replace(/\p{Script=Latin}+/gu, token => token.slice(0, 1) + '_'.repeat(Math.max(1, token.length - 1)));
  }

  function missingLetterMask(value) {
    let position = 0;
    return String(value || '').replace(/\p{Script=Latin}/gu, character => (++position % 2 ? character : '_'));
  }

  function buildPracticeWord(word, mode = 'study') {
    const spelling = String(word?.['单词'] || '');
    const zh = String(word?.['释义(中文)'] || '');
    const en = String(word?.['释义(英文)'] || '');
    const output = {word: spelling, zh, en, showPhonetic: true, mode};
    if (mode === 'en_to_zh') { output.zh = ''; output.en = ''; }
    else if (mode === 'zh_to_en') { output.word = '_'.repeat(Math.max(8, latinLength(spelling))); output.en = ''; output.showPhonetic = false; }
    else if (mode === 'first_letter') { output.word = firstLetterMask(spelling); output.showPhonetic = false; }
    else if (mode === 'missing_letters') { output.word = missingLetterMask(spelling); output.showPhonetic = false; }
    else if (mode === 'blank') { output.word = '________________'; output.zh = ''; output.en = ''; output.showPhonetic = false; }
    return output;
  }

  function parseIntervals(value) {
    const source = Array.isArray(value) ? value : String(value || '').split(/[\s,，;；]+/);
    const parsed = source.map(Number).filter(day => Number.isInteger(day) && day >= 0 && day <= 3650);
    return Array.from(new Set(parsed.length ? parsed : DEFAULT_INTERVALS)).sort((a, b) => a - b).slice(0, 30);
  }

  function parseDate(value) {
    const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
    return Number.isNaN(date.valueOf()) ? null : date;
  }

  function isoDate(date) {
    return new Date(date).toISOString().slice(0, 10);
  }

  function reviewSchedule(startDate, intervals = DEFAULT_INTERVALS) {
    const start = parseDate(startDate) || new Date(Date.UTC(new Date().getFullYear(), new Date().getMonth(), new Date().getDate()));
    return parseIntervals(intervals).map(day => ({day, date: isoDate(start.valueOf() + day * DAY)}));
  }

  function normalizeReviewItem(item = {}) {
    return {
      stage: Math.max(0, Math.trunc(Number(item.stage) || 0)),
      due: Number.isFinite(Number(item.due)) ? Number(item.due) : Date.now(),
      mistakes: Math.max(0, Math.trunc(Number(item.mistakes) || 0)),
      successes: Math.max(0, Math.trunc(Number(item.successes) || 0)),
      lastReviewed: Number.isFinite(Number(item.lastReviewed)) ? Number(item.lastReviewed) : 0,
      word: item.word
    };
  }

  function advanceReview(item, correct, now = Date.now(), intervals = DEFAULT_INTERVALS) {
    const result = normalizeReviewItem(item);
    result.lastReviewed = now;
    const parsed = parseIntervals(intervals).filter(day => day > 0);
    if (correct) {
      result.successes++;
      const delay = parsed[Math.min(result.stage, parsed.length - 1)] || 1;
      result.stage++;
      result.due = now + delay * DAY;
    } else {
      result.mistakes++;
      result.stage = Math.max(0, result.stage - 1);
      result.due = now + DAY;
    }
    return result;
  }

  function reviewPriority(item) {
    const value = normalizeReviewItem(item);
    const overdue = Math.max(0, (Date.now() - value.due) / DAY);
    return value.mistakes * 10 + overdue * 2 - value.successes;
  }

  function bookletOrder(pageCount) {
    const count = Math.max(0, Math.trunc(Number(pageCount) || 0));
    const padded = Math.ceil(count / 4) * 4;
    const page = number => number >= 1 && number <= count ? number : null;
    const pairs = [];
    for (let sheet = 0; sheet < padded / 4; sheet++) {
      pairs.push({sheet: sheet + 1, side: 'front', pages: [page(padded - sheet * 2), page(1 + sheet * 2)]});
      pairs.push({sheet: sheet + 1, side: 'back', pages: [page(2 + sheet * 2), page(padded - 1 - sheet * 2)]});
    }
    return pairs;
  }

  function escapeRegExp(value) { return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function blankExample(sentence, word) {
    const source = String(sentence || '');
    const target = String(word || '').trim();
    if (!target) return source;
    return source.replace(new RegExp(escapeRegExp(target), 'giu'), '_'.repeat(Math.max(4, latinLength(target))));
  }

  function explicitField(word, names) {
    for (const name of names) {
      const value = String(word?.[name] || '').trim();
      if (value) return value;
    }
    return '';
  }

  function morphology(word) {
    const spelling = String(word?.['单词'] || '').toLowerCase();
    const explicitRoot = explicitField(word, ['词根', 'root', '词根词缀']);
    const explicitAffix = explicitField(word, ['词缀', 'affix', '前后缀']);
    const family = explicitField(word, ['同族词', '派生词', 'family', 'wordFamily']);
    if (explicitRoot || explicitAffix || family) return {root: explicitRoot, affix: explicitAffix, family};
    const prefixes = ['anti','inter','trans','under','over','pre','post','re','un','dis','mis','non','sub'];
    const suffixes = ['ation','ition','ment','ness','able','ible','less','ful','ous','ive','ize','ise','ly','er','ist','al'];
    const prefix = prefixes.find(part => spelling.startsWith(part) && spelling.length > part.length + 3) || '';
    const suffix = suffixes.find(part => spelling.endsWith(part) && spelling.length > part.length + 3) || '';
    const root = spelling.slice(prefix.length, suffix ? -suffix.length : undefined);
    return {root: root && (prefix || suffix) ? root : '', affix: [prefix && `${prefix}-`, suffix && `-${suffix}`].filter(Boolean).join(' + '), family: ''};
  }

  function renderTemplate(template, context = {}) {
    const allowed = ['book','page','pages','date','words','student','class','mode'];
    return String(template || '').replace(/\{([a-z]+)\}/gi, (match, name) => allowed.includes(name.toLowerCase()) ? String(context[name.toLowerCase()] ?? '') : match);
  }

  function renderSafeTemplate(template, context = {}) { return escapeHtml(renderTemplate(template, context)); }

  function mergeWordbooks(books, mode = 'union') {
    const sources = Array.isArray(books) ? books.filter(book => book && Array.isArray(book.words)) : [];
    const byWord = new Map();
    sources.forEach((book, bookIndex) => {
      const sourceName = String(book.name || `词书${bookIndex + 1}`).slice(0, 120);
      for (const raw of book.words) {
        const normalized = key(raw?.['单词']);
        if (!normalized) continue;
        const existing = byWord.get(normalized);
        const rawSources = Array.isArray(raw?._sources) && raw._sources.length ? raw._sources.map(String) : [sourceName];
        if (existing) {
          rawSources.forEach(source => { if (!existing._sources.includes(source)) existing._sources.push(source); });
          for (const [field, value] of Object.entries(raw)) if (!existing[field] && value) existing[field] = value;
        } else byWord.set(normalized, {...raw, _sources:Array.from(new Set(rawSources))});
      }
    });
    const sourceNames = new Set(Array.from(byWord.values()).flatMap(word => word._sources));
    const required = Math.max(sources.length, sourceNames.size);
    return Array.from(byWord.values()).map(word => ({...word, _sourceTotal:required})).filter(word => {
      if (mode === 'intersection') return required > 0 && word._sources.length === required;
      if (mode === 'shared') return word._sources.length > 1;
      if (mode === 'unique') return word._sources.length === 1;
      return true;
    });
  }

  function csvCell(value, delimiter = ',') {
    const text = String(value ?? '').replace(/\r?\n/g, ' ');
    return text.includes(delimiter) || /["\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  }

  function exportRows(words) {
    return (Array.isArray(words) ? words : []).map(word => ({
      word: word?.['单词'] || '', us: word?.['美音'] || '', uk: word?.['英音'] || '',
      zh: word?.['释义(中文)'] || '', en: word?.['释义(英文)'] || '',
      example: word?.['例句'] || word?.['英文例句'] || '', difficulty: classifyDifficulty(word),
      sources: Array.isArray(word?._sources) ? word._sources.join(' / ') : ''
    }));
  }

  function toDelimited(words, delimiter = ',') {
    const rows = exportRows(words);
    const headers = ['单词','美音','英音','中文释义','英文释义','例句','难度','来源'];
    const fields = ['word','us','uk','zh','en','example','difficulty','sources'];
    return '\ufeff' + [headers, ...rows.map(row => fields.map(field => row[field]))]
      .map(row => row.map(value => csvCell(value, delimiter)).join(delimiter)).join('\r\n');
  }

  function toCsv(words) { return toDelimited(words, ','); }
  function toTsv(words) { return toDelimited(words, '\t'); }
  function toAnki(words) {
    return '\ufeff#separator:tab\r\n#html:false\r\n#columns:Front\tBack\tTags\r\n' + exportRows(words).map(row => {
      const front = [row.word, row.us || row.uk].filter(Boolean).join(' ');
      const back = [row.zh, row.en, row.example].filter(Boolean).join(' | ');
      return [front, back, `difficulty_${row.difficulty}`].map(value => csvCell(value, '\t')).join('\t');
    }).join('\r\n');
  }

  function sanitizeHttpUrl(value) {
    try {
      const url = new URL(String(value || ''));
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch { return ''; }
  }

  function pronunciationUrl(word, provider = 'youdao') {
    const target = encodeURIComponent(String(word || '').trim());
    if (!target) return '';
    if (provider === 'cambridge') return `https://dictionary.cambridge.org/dictionary/english/${target}`;
    if (provider === 'bing') return `https://www.bing.com/dict/search?q=${target}`;
    return `https://dict.youdao.com/result?word=${target}&lang=en`;
  }

  function qrImageUrl(url, size = 96) {
    const safe = sanitizeHttpUrl(url);
    if (!safe) return '';
    return `https://api.qrserver.com/v1/create-qr-code/?size=${clamp(size, 48, 240)}x${clamp(size, 48, 240)}&margin=0&data=${encodeURIComponent(safe)}`;
  }

  function buildDailyPlan(words, options = {}) {
    const list = Array.from(words || []);
    const start = parseDate(options.startDate) || parseDate(isoDate(new Date()));
    const deadline = parseDate(options.deadline);
    const requested = clamp(options.perDay || 20, 1, 1000);
    const calendarDays = deadline && deadline >= start ? Math.floor((deadline - start) / DAY) + 1 : Math.ceil(list.length / requested);
    const perDay = deadline ? Math.max(1, Math.ceil(list.length / Math.max(1, calendarDays))) : requested;
    const days = [];
    for (let offset = 0, index = 0; index < list.length; offset++, index += perDay) {
      const chunk = list.slice(index, index + perDay);
      days.push({day: offset + 1, date: isoDate(start.valueOf() + offset * DAY), start:index + 1, end:index + chunk.length, words:chunk});
    }
    return {startDate:isoDate(start), deadline:deadline ? isoDate(deadline) : (days.at(-1)?.date || isoDate(start)), perDay, totalDays:days.length, days};
  }

  function estimateCost({pages = 0, duplex = false, paperPrice = 0, inkPrice = 0, inkSaver = false, copies = 1} = {}) {
    const pageCount = Math.max(0, Math.ceil(Number(pages) || 0));
    const copyCount = clamp(copies || 1, 1, 1000);
    const sheets = (duplex ? Math.ceil(pageCount / 2) : pageCount) * copyCount;
    const printedPages = pageCount * copyCount;
    const paper = sheets * Math.max(0, Number(paperPrice) || 0);
    const ink = printedPages * Math.max(0, Number(inkPrice) || 0) * (inkSaver ? 0.55 : 1);
    return {pages:printedPages, sheets, paperCost:paper, inkCost:ink, total:paper + ink};
  }

  function calibrationConfig(input = {}) {
    return {
      scale: clamp(input.scale || 100, 90, 110),
      offsetX: clamp(input.offsetX || 0, -15, 15),
      offsetY: clamp(input.offsetY || 0, -15, 15)
    };
  }

  function prepareBatchQueue(items, limit = 10) {
    const seen = new Set(), output = [];
    for (const item of Array.from(items || [])) {
      const id = String(item?.path || item?.id || '').trim();
      if (!id || seen.has(id)) continue;
      seen.add(id); output.push(item);
      if (output.length >= clamp(limit, 1, 20)) break;
    }
    return output;
  }

  function shortcutAction(event) {
    const tag = String(event?.target?.tagName || '').toLowerCase();
    if (['input','textarea','select'].includes(tag) || event?.target?.isContentEditable) return null;
    const keyName = String(event?.key || '').toLowerCase();
    if (keyName === '/' && !event.ctrlKey && !event.metaKey && !event.altKey) return 'search';
    if ((event.ctrlKey || event.metaKey) && keyName === 'enter') return 'refresh';
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && keyName === 'd') return 'download';
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && keyName === 'l') return 'preflight';
    if (event.altKey && keyName === 'arrowright') return 'next';
    if (event.altKey && keyName === 'arrowleft') return 'previous';
    return null;
  }

  window.VocabAdvanced = Object.freeze({
    DAY, DEFAULT_INTERVALS, clamp, key, escapeHtml, hashSeed, seededShuffle, latinLength,
    difficultyScore, classifyDifficulty, englishDefinitions, wordWeight, smartPageGroups, overflowRecommendation,
    firstLetterMask, missingLetterMask, buildPracticeWord, parseIntervals, reviewSchedule,
    normalizeReviewItem, advanceReview, reviewPriority, bookletOrder, blankExample, morphology,
    renderTemplate, renderSafeTemplate, mergeWordbooks, exportRows, toCsv, toTsv, toAnki,
    sanitizeHttpUrl, pronunciationUrl, qrImageUrl, buildDailyPlan, estimateCost,
    calibrationConfig, prepareBatchQueue, shortcutAction
  });
})();
