/* Daily Playlist Player — vanilla frontend.
 *
 * Features:
 * - Daily pick with 7 rotating styles (style comes from /api/today).
 * - Bilibili full audio through the server proxy (/api/audio-stream),
 *   30s iTunes preview as fallback.
 * - YouTube: one persistent iframe, never removed. Switching songs
 *   navigates the frame itself (contentWindow.location.replace) instead
 *   of rewriting its src attribute — rewriting src is ignored by some
 *   app webviews once the frame has loaded. No autoplay, no commands:
 *   the user taps the video's own play button.
 * - Companion sound: in YouTube mode the video frame cannot be relied
 *   on for sound in some webviews, so an optional toggle plays sound
 *   through this page's own <audio> channel instead.
 * - Lyrics: synced lines when LRCLIB has timestamps; plain-only
 *   lyrics get a client-side estimated timeline (total duration
 *   distributed across lines weighted by line length), labelled as an
 *   estimate. Tap a line to seek.
 * - Likes persist server-side; searchable full library.
 * - Landscape mode: automatic on orientation change, plus a manual
 *   toggle button.
 */
(function () {
  'use strict';

  var audio = document.getElementById('audio');

  var state = {
    song: null,
    source: 'auto',       // auto | bilibili | youtube
    mode: 'none',         // bilibili | youtube | preview | none
    companion: false,
    ytVideoId: null,
    ytFrame: null,        // created once, never removed
    lyrics: [],           // [{t, text}]
    lyricsEstimated: false,
    liked: {},
    library: [],
    tab: 'all',
    playing: false,
    duration: 0,
    currentLine: -1,
  };

  function el(id) { return document.getElementById(id); }

  function api(path, opts) {
    return fetch(path, opts).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
  }

  function setStatus(text) { el('statusLine').textContent = text || ''; }

  /* ---------------- daily pick & song loading ---------------- */

  function loadToday() {
    return api('/api/today').then(function (today) {
      el('todayLine').textContent = today.date + ' · 今日风格：' + today.style_name;
      document.body.dataset.style = today.style;
      return loadSong(today.song);
    }).catch(function (err) {
      setStatus('今日推荐加载失败：' + err.message);
    });
  }

  function loadSong(song) {
    state.song = song;
    state.mode = 'none';
    state.ytVideoId = null;
    state.lyrics = [];
    state.lyricsEstimated = false;
    state.currentLine = -1;
    state.duration = song.duration_sec || 0;
    el('songTitle').textContent = song.title;
    el('songArtist').textContent = song.artist;
    el('songStyle').textContent = '风格：' + song.styles.join(' / ');
    el('discLabel').textContent = song.title.slice(0, 1);
    el('durTime').textContent = fmt(state.duration);
    el('curTime').textContent = '0:00';
    el('seek').value = 0;
    updateLikeBtn();
    renderLyrics([], false);
    loadLyrics(song);
    loadPreview(song);
    return prepareAudio(song, false);
  }

  function loadPreview(song) {
    api('/api/preview?id=' + encodeURIComponent(song.id)).then(function (t) {
      var cover = el('cover');
      if (t.artwork_url) { cover.src = t.artwork_url; cover.hidden = false; }
      else { cover.hidden = true; }
      state.previewUrl = t.preview_url || '';
    }).catch(function () { /* artwork is optional */ });
  }

  /* ---------------- audio sources ---------------- */

  function showYtBox(show) {
    el('ytBox').hidden = !show;
    el('ytHint').hidden = !show;
    el('companionWrap').hidden = !show;
  }

  function prepareAudio(song, autoplay) {
    showYtBox(false);
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
    if (state.source === 'bilibili') return useBilibili(song, autoplay);
    if (state.source === 'youtube') return useYoutube(song, autoplay);
    // auto: Bilibili first, then YouTube, then 30s preview.
    return useBilibili(song, autoplay).catch(function () {
      return useYoutube(song, autoplay);
    }).catch(function () {
      return usePreview(song, autoplay);
    });
  }

  function useBilibili(song, autoplay) {
    setStatus('正在解析哔哩哔哩音频…');
    return api('/api/audio?id=' + encodeURIComponent(song.id)).then(function () {
      state.mode = 'bilibili';
      audio.src = '/api/audio-stream?id=' + encodeURIComponent(song.id);
      setStatus('哔哩哔哩 · 整首播放');
      if (autoplay) return playAudio();
    });
  }

  function ytEmbedUrl(videoId) {
    return 'https://www.youtube.com/embed/' + videoId + '?rel=0&playsinline=1';
  }

  function ytNavigate(videoId) {
    // The frame stays mounted forever; only its own browsing context
    // moves to the new video. Rewriting the src attribute is ignored
    // by some app webviews once the frame has loaded.
    var url = ytEmbedUrl(videoId);
    if (state.ytFrame) {
      try {
        state.ytFrame.contentWindow.location.replace(url);
      } catch (e) {
        state.ytFrame.src = url; // fallback when replace is unavailable
      }
    } else {
      var frame = document.createElement('iframe');
      frame.src = url;
      frame.allow = 'accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture';
      frame.allowFullscreen = true;
      frame.title = 'YouTube video player';
      el('ytBox').appendChild(frame);
      state.ytFrame = frame;
    }
    state.ytVideoId = videoId;
  }

  function useYoutube(song, autoplay) {
    setStatus('正在找这首歌的 YouTube 视频…');
    return api('/api/youtube?id=' + encodeURIComponent(song.id)).then(function (v) {
      state.mode = 'youtube';
      showYtBox(true);
      ytNavigate(v.video_id);
      setStatus('YouTube · ' + v.title);
      if (state.companion) return useCompanionAudio(song, autoplay);
      if (autoplay) setStatus('YouTube · 点视频上的播放键开始播放');
    });
  }

  function useCompanionAudio(song, autoplay) {
    // Sound through this page's own audio channel while the video plays.
    return useBilibili(song, autoplay).catch(function () {
      return usePreview(song, autoplay);
    });
  }

  function usePreview(song, autoplay) {
    return api('/api/preview?id=' + encodeURIComponent(song.id)).then(function (t) {
      if (!t.preview_url) throw new Error('no preview available');
      state.mode = 'preview';
      audio.src = t.preview_url;
      setStatus('仅 30 秒试听（无哔哩哔哩 / YouTube 可用版本）');
      if (autoplay) return playAudio();
    });
  }

  /* ---------------- transport ---------------- */

  function playAudio() {
    return audio.play().then(function () {
      state.playing = true;
      syncTransport();
    }).catch(function (err) {
      setStatus('播放失败：' + err.message);
    });
  }

  function togglePlay() {
    if (state.mode === 'youtube' && !state.companion) {
      setStatus('YouTube 模式：点视频上的播放键开始播放，或打开「伴随声音」。');
      return;
    }
    if (state.playing) {
      audio.pause();
      state.playing = false;
    } else {
      playAudio();
    }
    syncTransport();
  }

  function syncTransport() {
    el('playBtn').textContent = state.playing ? '⏸' : '▶';
    el('turntable').classList.toggle('playing', state.playing);
  }

  audio.addEventListener('ended', function () { nextSong(true); });
  audio.addEventListener('timeupdate', function () {
    var dur = audio.duration || state.duration || 0;
    if (dur > 0) {
      el('seek').value = Math.round((audio.currentTime / dur) * 1000);
      el('curTime').textContent = fmt(audio.currentTime);
      el('durTime').textContent = fmt(dur);
    }
    highlightLyric(audio.currentTime);
  });
  audio.addEventListener('loadedmetadata', function () {
    if (audio.duration && isFinite(audio.duration)) {
      state.duration = audio.duration;
      el('durTime').textContent = fmt(state.duration);
      if (state.lyricsEstimated) rebuildEstimatedTimeline();
    }
  });
  audio.addEventListener('error', function () {
    if (state.mode === 'bilibili' && state.song) {
      setStatus('哔哩哔哩音频加载失败，改用 30 秒试听。');
      usePreview(state.song, true);
    }
  });

  el('seek').addEventListener('input', function () {
    if (state.mode === 'youtube' && !state.companion) return; // no audio channel to seek
    var dur = audio.duration || state.duration || 0;
    if (dur > 0 && state.mode !== 'none') {
      audio.currentTime = (Number(el('seek').value) / 1000) * dur;
    }
  });

  function stepSong(dir, autoplay) {
    if (!state.library.length || !state.song) return;
    var idx = -1;
    state.library.forEach(function (s, i) { if (s.id === state.song.id) idx = i; });
    var next = state.library[(idx + dir + state.library.length) % state.library.length];
    loadSong(next).then(function () { if (autoplay) togglePlay(); });
  }
  function nextSong(autoplay) { stepSong(1, autoplay); }
  function prevSong() { stepSong(-1, true); }

  el('playBtn').addEventListener('click', togglePlay);
  el('nextBtn').addEventListener('click', function () { nextSong(true); });
  el('prevBtn').addEventListener('click', prevSong);

  /* ---------------- lyrics ---------------- */

  function buildEstimatedTimeline(lines, totalSec) {
    // Plain-only lyrics: distribute the total duration across lines,
    // weighted by line length. Positions are estimates, labelled as such.
    var weights = lines.map(function (l) { return Math.max(l.length, 1); });
    var sum = weights.reduce(function (a, b) { return a + b; }, 0) || 1;
    var t = 0;
    return lines.map(function (l, i) {
      var item = { t: t, text: l };
      t += (weights[i] / sum) * totalSec;
      return item;
    });
  }

  function rebuildEstimatedTimeline() {
    if (!state.lyricsEstimated || !state.plainLines) return;
    state.lyrics = buildEstimatedTimeline(state.plainLines, state.duration || 0);
    renderLyrics(state.lyrics, true);
  }

  function loadLyrics(song) {
    api('/api/lyrics?id=' + encodeURIComponent(song.id)).then(function (l) {
      if (l.has_timestamps && l.synced && l.synced.length) {
        state.lyrics = l.synced.map(function (p) { return { t: p[0], text: p[1] }; });
        state.lyricsEstimated = false;
        renderLyrics(state.lyrics, false);
      } else if (l.plain) {
        var lines = l.plain.split('\n').map(function (x) { return x.trim(); })
          .filter(function (x) { return x.length > 0; });
        state.plainLines = lines;
        state.lyricsEstimated = true;
        state.lyrics = buildEstimatedTimeline(lines, song.duration_sec || 180);
        renderLyrics(state.lyrics, true);
      } else {
        renderLyrics([], false);
      }
    }).catch(function () { renderLyrics([], false); });
  }

  function renderLyrics(lines, estimated) {
    var list = el('lyricsList');
    list.innerHTML = '';
    el('noLyrics').hidden = lines.length > 0;
    el('lyricsNote').textContent = estimated
      ? '歌词时间轴为估算（按行长分配时长），位置仅供参考。'
      : '';
    lines.forEach(function (line, i) {
      var li = document.createElement('li');
      li.textContent = line.text;
      li.dataset.index = i;
      li.addEventListener('click', function () {
        if (state.mode !== 'none' && audio.duration) {
          audio.currentTime = line.t;
          if (!state.playing) playAudio();
        }
      });
      list.appendChild(li);
    });
    state.currentLine = -1;
  }

  function highlightLyric(now) {
    if (!state.lyrics.length) return;
    var idx = -1;
    for (var i = 0; i < state.lyrics.length; i++) {
      if (state.lyrics[i].t <= now) idx = i; else break;
    }
    if (idx === state.currentLine) return;
    state.currentLine = idx;
    var items = el('lyricsList').children;
    for (var j = 0; j < items.length; j++) {
      items[j].classList.toggle('active', j === idx);
    }
    if (idx >= 0 && state.playing) {
      items[idx].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  /* ---------------- likes & library ---------------- */

  function updateLikeBtn() {
    var liked = !!state.liked[state.song ? state.song.id : ''];
    el('likeBtn').textContent = liked ? '♥' : '♡';
    el('likeBtn').classList.toggle('liked', liked);
  }

  el('likeBtn').addEventListener('click', function () {
    if (!state.song) return;
    api('/api/like', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: state.song.id }),
    }).then(function (r) {
      state.liked[state.song.id] = r.liked;
      updateLikeBtn();
      if (state.tab === 'liked') renderLibrary();
    });
  });

  function renderLibrary() {
    var list = el('songList');
    list.innerHTML = '';
    var songs = state.tab === 'liked'
      ? state.library.filter(function (s) { return state.liked[s.id]; })
      : state.library;
    if (!songs.length) {
      var empty = document.createElement('li');
      empty.textContent = state.tab === 'liked' ? '心选歌单还是空的，点 ♡ 收藏一首吧。' : '没有找到这首歌。';
      list.appendChild(empty);
      return;
    }
    songs.forEach(function (song) {
      var li = document.createElement('li');
      if (state.song && song.id === state.song.id) li.classList.add('playing');
      var left = document.createElement('span');
      left.innerHTML = '<span class="t"></span> · <span class="a"></span>';
      left.querySelector('.t').textContent = song.title;
      left.querySelector('.a').textContent = song.artist;
      var mark = document.createElement('span');
      mark.className = 'like-mark';
      mark.textContent = state.liked[song.id] ? '♥' : '';
      li.appendChild(left);
      li.appendChild(mark);
      li.addEventListener('click', function () {
        loadSong(song).then(function () { togglePlay(); });
      });
      list.appendChild(li);
    });
  }

  function loadLibrary(query) {
    var url = '/api/library' + (query ? '?q=' + encodeURIComponent(query) : '');
    return api(url).then(function (r) {
      state.library = r.songs;
      renderLibrary();
    });
  }

  el('search').addEventListener('input', function () {
    loadLibrary(el('search').value.trim());
  });

  document.querySelectorAll('.tabs button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('.tabs button').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      state.tab = btn.dataset.tab;
      renderLibrary();
    });
  });

  /* ---------------- source switch & companion ---------------- */

  document.querySelectorAll('#sourceSwitch button').forEach(function (btn) {
    btn.addEventListener('click', function () {
      document.querySelectorAll('#sourceSwitch button').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      state.source = btn.dataset.source;
      try { localStorage.setItem('playlist-source', state.source); } catch (e) { /* ignore */ }
      if (state.song) prepareAudio(state.song, state.playing);
    });
  });

  el('companionToggle').addEventListener('change', function () {
    state.companion = el('companionToggle').checked;
    if (!state.song) return;
    if (state.mode === 'youtube') {
      if (state.companion) useCompanionAudio(state.song, state.playing);
      else { audio.pause(); state.playing = false; syncTransport(); }
    }
  });

  try {
    var saved = localStorage.getItem('playlist-source');
    if (saved === 'bilibili' || saved === 'youtube' || saved === 'auto') {
      state.source = saved;
      document.querySelectorAll('#sourceSwitch button').forEach(function (b) {
        b.classList.toggle('active', b.dataset.source === saved);
      });
    }
  } catch (e) { /* ignore */ }

  /* ---------------- landscape ---------------- */

  function applyLandscape() {
    var wide = window.matchMedia('(orientation: landscape)').matches;
    document.body.classList.toggle('landscape', wide || document.body.classList.contains('landscape-manual'));
  }
  el('landscapeBtn').addEventListener('click', function () {
    document.body.classList.toggle('landscape-manual');
    document.body.classList.add('no-auto-landscape');
    applyLandscape();
    el('landscapeBtn').textContent = document.body.classList.contains('landscape') ? '竖屏模式' : '横屏模式';
  });
  window.addEventListener('orientationchange', applyLandscape);
  window.addEventListener('resize', applyLandscape);

  /* ---------------- boot ---------------- */

  api('/api/likes').then(function (r) {
    r.liked.forEach(function (s) { state.liked[s.id] = true; });
  }).catch(function () { /* likes are optional */ });
  loadLibrary('').then(loadToday);
  applyLandscape();
})();
