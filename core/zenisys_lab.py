"""
Zenisys Lab — rebuilt with CONTINUOUS MUSIC as the foundation.

The interactive sounds are nothing without continuous, warm, evolving music
underneath. The music is the bed that NEVER stops. Touch, trace, and voice
layer ON TOP of it and steer it. And when the person drifts (stops
interacting), the system actively reaches for them — the music shifts, a
light moves, and a real SPOKEN voice says real words.

This lives inside InnerLight.
"""

ZENISYS_LAB_PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zenisys Lab — Continuous Anchor</title>
<style>
  * { box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    background:#0c1322; color:#e8eef5; min-height:100vh; overflow:hidden; touch-action:none; }
  .top { padding:14px 18px 6px; text-align:center; }
  .top h1 { font-weight:300; letter-spacing:2px; margin:0; font-size:20px; }
  .top p { color:#8aa3c4; font-size:13px; margin:5px 0 0; }
  .modes { display:flex; gap:8px; justify-content:center; flex-wrap:wrap; padding:8px 12px 12px; }
  .mode-btn { background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.20);
    color:#dce8f5; padding:9px 15px; border-radius:999px; cursor:pointer; font-size:13px; font-weight:500; }
  .mode-btn.active { background:#6fb3d4; color:#0c1322; font-weight:700; border-color:#6fb3d4; }
  #stage { position:fixed; inset:0; top:128px; }
  #calm-video { position:fixed; inset:0; top:128px; width:100%; height:100%;
    object-fit:cover; opacity:0; transition:opacity 2s ease; z-index:0; }
  #calm-video.visible { opacity:0.55; }
  canvas { display:block; width:100%; height:100%; position:relative; z-index:1; }
  .scene-bar { position:fixed; bottom:64px; left:0; right:0; display:flex; gap:8px;
    justify-content:center; flex-wrap:wrap; z-index:6; }
  .scene-btn { background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.2);
    color:#cdddee; padding:7px 13px; border-radius:999px; cursor:pointer; font-size:12px; }
  .scene-btn.active { background:rgba(111,179,212,0.7); color:#0c1322; font-weight:700; }
  .musicbar { position:fixed; top:128px; left:0; right:0; display:flex; gap:14px; justify-content:center;
    align-items:center; padding:8px; background:rgba(12,19,34,0.6); z-index:5; flex-wrap:wrap; }
  .musicbar label { font-size:12px; color:#9fb6d0; }
  .musicbar select { background:#1a2744; color:#e8eef5; border:1px solid #3a4a66; border-radius:8px; padding:6px 10px; font-size:13px; }
  .hint { position:fixed; bottom:22px; left:0; right:0; text-align:center; color:#8aa3c4;
    font-size:14px; pointer-events:none; padding:0 24px; line-height:1.5; }
  .startgate { position:fixed; inset:0; background:linear-gradient(180deg,#0c1322,#16243f);
    display:flex; flex-direction:column; align-items:center; justify-content:center; z-index:50; cursor:pointer; padding:24px; }
  .startgate h2 { font-weight:300; letter-spacing:2px; font-size:30px; margin:0 0 4px; }
  .startgate .sub { color:#6fb3d4; font-size:14px; letter-spacing:1px; margin-bottom:18px; }
  .startgate .go { background:#6fb3d4; color:#0c1322; border:0; padding:16px 48px; border-radius:999px;
    font-size:17px; font-weight:700; cursor:pointer; margin-top:18px; }
  .startgate p { color:#8aa3c4; max-width:440px; text-align:center; font-size:14px; line-height:1.7; }
</style></head>
<body>
  <div class="startgate" id="gate" onclick="labStart()">
    <h2>ZENISYS</h2>
    <div class="sub">CONTINUOUS ANCHOR</div>
    <p>Warm music begins and never stops. Touch, trace, or speak &mdash; the sound answers you and bends to you. If you drift away, it gently reaches back for you with light, sound, and a calm voice. Headphones recommended.</p>
    <button class="go">Begin</button>
  </div>
  <div class="top">
    <h1>ZENISYS &mdash; CONTINUOUS ANCHOR</h1>
    <p id="modeDesc">Music is always playing. Touch anywhere &mdash; it answers you.</p>
  </div>
  <div class="modes" id="modes"></div>
  <div class="musicbar" id="musicbar" style="display:none">
    <label>Underlying feeling:</label>
    <select id="moodSel" onchange="changeMood(this.value)">
      <option value="calm">Calm</option>
      <option value="peaceful">Peaceful</option>
      <option value="sadness">Tender / Sad</option>
      <option value="grief">Grief</option>
      <option value="hope">Hope</option>
      <option value="numbness">Gentle wakening</option>
      <option value="overwhelm">Spacious / Quiet</option>
    </select>
    <label><input type="checkbox" id="binaural" onchange="toggleBinaural()"> Binaural</label>
  </div>
  <video id="calm-video" muted loop playsinline></video>
  <div id="stage"><canvas id="cv"></canvas></div>
  <div class="scene-bar" id="scene-bar" style="display:none">
    <button class="scene-btn active" data-scene="none" onclick="setScene('none')">Light only</button>
    <button class="scene-btn" data-scene="water" onclick="setScene('water')">Water</button>
    <button class="scene-btn" data-scene="clouds" onclick="setScene('clouds')">Clouds</button>
    <button class="scene-btn" data-scene="candle" onclick="setScene('candle')">Candle</button>
    <button class="scene-btn" data-scene="rain" onclick="setScene('rain')">Rain</button>
  </div>
  <div class="hint" id="hint">Touch anywhere &mdash; the music answers you</div>

<script src="https://cdn.jsdelivr.net/npm/tone@14/build/Tone.js"></script>
<script>
let AC=null, started=false, mode='anchor';
const cv=document.getElementById('cv'); const ctx=cv.getContext('2d');
function resize(){ cv.width=window.innerWidth; cv.height=window.innerHeight-128; }
window.addEventListener('resize',resize); resize();

const MODES=[
  {id:'anchor', name:'Continuous Anchor', desc:'Music always plays. Touch anywhere; if you drift, it reaches back with light, sound, and a calm voice.'},
  {id:'trace',  name:'Trace', desc:'Drag your finger over the music \u2014 a voice rises and falls with you'},
  {id:'call',   name:'Call & Answer', desc:'Tap over the music \u2014 a gentle voice answers each tap'},
  {id:'hum',    name:'Hum Back', desc:'Hum or speak \u2014 the music mirrors your pitch'},
  {id:'mirror', name:'Mirror', desc:'Move \u2014 the world follows your lead a moment later'},
];

// ---- CONTINUOUS ZENISYS MUSIC — the foundation, never stops ----
const ZMUSIC = { pad:null, filter:null, reverb:null, gain:null, loop:null,
  chords:null, idx:0, mood:'calm', binaural:null, started:false };
const MOOD_PROFILES = {
  calm:     { key:'C', scale:'major',  bpm:62, chordSecs:8,  bright:0.4,  vol:0.5 },
  peaceful: { key:'G', scale:'major',  bpm:58, chordSecs:10, bright:0.35, vol:0.48 },
  sadness:  { key:'A', scale:'minor',  bpm:64, chordSecs:9,  bright:0.35, vol:0.5 },
  grief:    { key:'F', scale:'minor',  bpm:58, chordSecs:11, bright:0.28, vol:0.46 },
  hope:     { key:'D', scale:'major',  bpm:70, chordSecs:7,  bright:0.55, vol:0.52 },
  numbness: { key:'C', scale:'lydian', bpm:64, chordSecs:9,  bright:0.42, vol:0.5 },
  overwhelm:{ key:'G', scale:'major',  bpm:60, chordSecs:12, bright:0.3,  vol:0.42 },
};
const SCALE_INTERVALS = { major:[0,2,4,5,7,9,11], minor:[0,2,3,5,7,8,10], dorian:[0,2,3,5,7,9,10], lydian:[0,2,4,6,7,9,11] };
const NOTE_BASE = {C:0,'C#':1,D:2,'D#':3,E:4,F:5,'F#':6,G:7,'G#':8,A:9,'A#':10,B:11};
function noteName(s,o){const n=['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];return n[((s%12)+12)%12]+o;}
function buildChords(keyRoot,scale){
  const root=NOTE_BASE[keyRoot]!=null?NOTE_BASE[keyRoot]:0;
  const iv=SCALE_INTERVALS[scale]||SCALE_INTERVALS.major;
  return [0,3,5,4].map(deg=>{
    const r=root+iv[deg%iv.length], t=root+iv[(deg+2)%iv.length], f=root+iv[(deg+4)%iv.length];
    return [noteName(r,3),noteName(t,4),noteName(f,4),noteName(r,4)];
  });
}
function startMusic(mood){
  const p = MOOD_PROFILES[mood] || MOOD_PROFILES.calm; ZMUSIC.mood = mood;
  if(!ZMUSIC.started){
    ZMUSIC.gain = new Tone.Gain(p.vol).toDestination();
    ZMUSIC.reverb = new Tone.Reverb({decay:9, wet:0.55}).connect(ZMUSIC.gain);
    ZMUSIC.filter = new Tone.Filter({type:'lowpass', frequency:600+p.bright*2800, rolloff:-24}).connect(ZMUSIC.reverb);
    ZMUSIC.pad = new Tone.PolySynth(Tone.Synth, { oscillator:{type:'sine'},
      envelope:{attack:2.5, decay:1.5, sustain:0.6, release:7}, volume:-22 }).connect(ZMUSIC.filter);
    ZMUSIC.started = true;
  }
  applyMusic(p);
}
function applyMusic(p){
  if(ZMUSIC.gain) ZMUSIC.gain.gain.rampTo(p.vol, 3);
  if(ZMUSIC.filter) ZMUSIC.filter.frequency.rampTo(600+p.bright*2800, 4);
  Tone.Transport.bpm.rampTo(p.bpm, 6);
  ZMUSIC.chords = buildChords(p.key, p.scale); ZMUSIC.idx = 0;
  if(ZMUSIC.loop){ ZMUSIC.loop.stop(); ZMUSIC.loop.dispose(); }
  const interval = Math.max(2, p.chordSecs);
  ZMUSIC.loop = new Tone.Loop((time)=>{
    const chord = ZMUSIC.chords[ZMUSIC.idx % ZMUSIC.chords.length];
    ZMUSIC.pad.triggerAttackRelease(chord, interval*0.92, time); ZMUSIC.idx++;
  }, interval);
  ZMUSIC.loop.start(0);
  if(Tone.Transport.state!=='started') Tone.Transport.start();
}
function changeMood(mood){ const p=MOOD_PROFILES[mood]||MOOD_PROFILES.calm; applyMusic(p); ZMUSIC.mood=mood; }
function toggleBinaural(){
  const on=document.getElementById('binaural').checked;
  if(ZMUSIC.binaural){ try{ZMUSIC.binaural.forEach(o=>o.stop());}catch(e){} ZMUSIC.binaural=null; }
  if(on && AC){
    const carrier=160, beat=8;
    const ear=(f,pan)=>{const o=AC.createOscillator();o.frequency.value=f;o.type='sine';
      const g=AC.createGain();g.gain.value=0.03;const pn=AC.createStereoPanner();pn.pan.value=pan;
      o.connect(g);g.connect(pn);pn.connect(AC.destination);o.start();return o;};
    ZMUSIC.binaural=[ear(carrier,-1),ear(carrier+beat,1)];
  }
}

// ---- INTERACTION VOICES (layered on top of the music) ----
const PENT=[262,294,330,392,440,494,587];
function nearestPent(f){let b=PENT[0],d=1e9;PENT.forEach(p=>{if(Math.abs(p-f)<d){d=Math.abs(p-f);b=p;}});return b;}
let lastVoiceT=0;
function voice(freq,pan,dur,vol){
  const o=AC.createOscillator();o.type='triangle';o.frequency.value=freq;
  const g=AC.createGain();g.gain.value=0; const p=AC.createStereoPanner();p.pan.value=pan||0;
  o.connect(g);g.connect(p);p.connect(AC.destination);o.start();
  const now=AC.currentTime;
  g.gain.setValueAtTime(0,now);
  g.gain.linearRampToValueAtTime(vol||0.18,now+0.04);
  g.gain.exponentialRampToValueAtTime(0.0008,now+(dur||0.7));
  o.stop(now+(dur||0.7)+0.05);
}
function voiceThrottled(freq,pan){const n=performance.now();if(n-lastVoiceT<130)return;lastVoiceT=n;voice(freq,pan,0.4,0.12);}

let traceOsc=null,traceGain=null,tracePan=null;
function ensureTrace(){ if(traceOsc)return;
  traceOsc=AC.createOscillator();traceOsc.type='triangle';
  traceGain=AC.createGain();traceGain.gain.value=0; tracePan=AC.createStereoPanner();
  traceOsc.connect(traceGain);traceGain.connect(tracePan);tracePan.connect(AC.destination);traceOsc.start();
}
function traceMove(x,y){ ensureTrace();
  const freq=180+(1-y/cv.height)*460, pan=(x/cv.width)*2-1;
  traceOsc.frequency.linearRampToValueAtTime(freq,AC.currentTime+0.05);
  tracePan.pan.linearRampToValueAtTime(pan,AC.currentTime+0.05);
  traceGain.gain.linearRampToValueAtTime(0.2,AC.currentTime+0.05);
}
function traceRelease(){ if(traceGain) traceGain.gain.linearRampToValueAtTime(0,AC.currentTime+0.4); }

function callTap(x,y){
  const base=nearestPent(260+(1-y/cv.height)*360), pan=(x/cv.width)*2-1;
  voice(base,pan,0.55,0.2);
  setTimeout(()=>voice(base*1.5,-pan,0.7,0.15),300);
  ripple(x,y,'#6fb3d4');
}

let humStream=null,humAnalyser=null,humData=null,humOsc=null,humGain=null;
async function startHum(){ try{
  humStream=await navigator.mediaDevices.getUserMedia({audio:true});
  const src=AC.createMediaStreamSource(humStream);
  humAnalyser=AC.createAnalyser();humAnalyser.fftSize=2048;src.connect(humAnalyser);
  humData=new Float32Array(humAnalyser.fftSize);
  humOsc=AC.createOscillator();humOsc.type='sine';humGain=AC.createGain();humGain.gain.value=0;
  humOsc.connect(humGain);humGain.connect(AC.destination);humOsc.start();
}catch(e){ document.getElementById('hint').textContent='Mic not available \u2014 try another mode'; } }
function humAnalyze(){ if(!humAnalyser)return null;
  humAnalyser.getFloatTimeDomainData(humData);
  let rms=0;for(let i=0;i<humData.length;i++)rms+=humData[i]*humData[i];rms=Math.sqrt(rms/humData.length);
  if(rms<0.01){ if(humGain)humGain.gain.linearRampToValueAtTime(0,AC.currentTime+0.1);return null; }
  let off=-1,best=0;
  for(let o=40;o<1000;o++){let c=0;for(let i=0;i<humData.length-o;i++)c+=humData[i]*humData[i+o];if(c>best){best=c;off=o;}}
  if(off<0)return null;
  const freq=AC.sampleRate/off; if(freq<70||freq>700)return null;
  const target=nearestPent(freq);
  humOsc.frequency.linearRampToValueAtTime(target,AC.currentTime+0.08);
  humGain.gain.linearRampToValueAtTime(0.18,AC.currentTime+0.08);
  return {target};
}

let mirrorTrail=[];
function mirrorMove(x,y){ mirrorTrail.push({x,y,t:performance.now()}); if(mirrorTrail.length>120)mirrorTrail.shift(); }

// ---- ANCHOR layer: reaches back when the person drifts ----
let lastTouchT=0, callLight={x:0,y:0,active:false,t:0}, anchorActive=false;
let promptShown='', promptIdx=0, speaking=false, lastPromptT=0;
// ============================================================
// GENERATIVE CALMING RESPONDER — effectively INFINITE, never a fixed list.
// Instead of storing finished sentences, we store human BUILDING BLOCKS and
// assemble a fresh line every time. A handful of pieces combine into thousands
// of natural variations, so it never runs dry and never becomes wallpaper.
// Three intents woven together: REASSURE, GROUND, gently DISTRACT.
// We are not clinicians — these are warm, human, non-diagnostic, never advice.
// ============================================================
const G = {
  // warm openers (some casual/human, some soft)
  open: ['Hey,', 'Listen,', 'Okay,', '', '', 'Right now,', 'Just for this moment,',
         'Stay with me,', 'I am here,', 'Breathe with me,', 'It is okay,'],
  // reassurance cores
  reassure: ['you are not alone', 'you have got this', 'I am right here with you',
    'I am not going anywhere', 'you are safe right now', 'we will get through this',
    'this moment will pass', 'you matter', 'I have got you', 'you are doing okay',
    'help is on the way', 'you are stronger than this moment', 'I see you',
    'you do not have to carry this by yourself', 'hold on, help is coming'],
  // grounding cues (a thing to notice or feel — present tense, gentle)
  ground: ['feel your feet on the floor', 'notice the light in front of you',
    'feel the air on your skin', 'press your hand on something solid',
    'feel where you are sitting', 'let your shoulders drop',
    'notice one thing you can see', 'feel your breath go in and out',
    'listen for the sound beneath everything', 'touch something close to you',
    'unclench your hands', 'feel the weight of your body'],
  // gentle distraction / small jobs (redirect attention, give the mind a task)
  distract: ['can you find the light?', 'trace a slow circle with your finger',
    'tap along with the sound', 'what color is the glow right now?',
    'follow the light with your eyes', 'hum one note with the music',
    'count slowly to five with me', 'move your hand toward the light',
    'can you make the sound rise?', 'find the warm spot on the screen',
    'catch the light when it moves', 'draw a slow line with your finger',
    'tell me one color you can see', 'breathe out slow, like a candle'],
  // soft closers
  close: ['', '', 'I am here.', 'Stay with me.', 'Right here.', 'You are okay.',
          'I have got you.', 'Just breathe.', 'We are okay.'],
};
function pick(a){ return a[Math.floor(Math.random()*a.length)]; }
function cap(s){ return s.charAt(0).toUpperCase()+s.slice(1); }
let lastGen='';
function composeCalming(){
  // randomly choose a SHAPE so structure varies too, not just words
  const shape = Math.random();
  let core;
  if(shape < 0.38){               // reassurance-led
    core = pick(G.reassure);
  } else if(shape < 0.68){        // grounding-led
    core = pick(G.ground);
  } else if(shape < 0.92){        // distraction-led
    core = pick(G.distract);
  } else {                        // blend two intents into one line
    core = pick(G.reassure) + ', and ' + pick(G.distract);
  }
  const open = pick(G.open);
  const close = pick(G.close);
  let body = (open ? open + ' ' : '') + core;
  body = cap(body.trim());
  // add a period only if it doesn't already end in punctuation
  if(!/[.?!]$/.test(body)) body += '.';
  let line = body;
  if(close && Math.random() < 0.5) line += ' ' + close;
  // never the exact same line twice in a row
  if(line === lastGen) return composeCalming();
  lastGen = line;
  return line;
}
// Kept name nextPrompt() so the rest of the anchor calls it unchanged.
// The LOCAL composer is always the instant floor (never waits on a network).
// Optionally, a fresh line can be fetched in the BACKGROUND and queued for the
// NEXT prompt — so we get unlimited variety without ever stalling in a crisis.
let aiLineQueue = [];
function nextPrompt(){
  // If a background line is ready, occasionally use it for extra variety
  if(aiLineQueue.length && Math.random() < 0.5){
    const v = aiLineQueue.shift();
    fetchAnchorLine(); // refill in background
    if(v && v !== lastGen){ lastGen = v; return v; }
  }
  fetchAnchorLine(); // keep the queue warm, never blocks
  return composeCalming();
}
function fetchAnchorLine(){
  if(aiLineQueue.length > 3) return; // keep a small buffer
  try{
    fetch('/api/anchor/line').then(r=>r.json()).then(d=>{
      if(d && d.line) aiLineQueue.push(d.line);
    }).catch(()=>{});
  }catch(e){}
}
function speak(text){
  if(speaking || !('speechSynthesis' in window)) return;
  try{
    const u=new SpeechSynthesisUtterance(text);
    u.rate=0.82; u.pitch=1.0; u.volume=0.9;
    u.onend=()=>{ speaking=false; };
    speaking=true; window.speechSynthesis.speak(u);
  }catch(e){ speaking=false; }
}
function startAnchor(){ anchorActive=true; lastTouchT=performance.now(); callLight={x:cv.width/2,y:cv.height/2,active:false,t:0}; }
function stopAnchor(){ anchorActive=false; if('speechSynthesis' in window) window.speechSynthesis.cancel(); }
function anchorTouch(x,y){
  lastTouchT=performance.now();
  voice(nearestPent(260+(1-y/cv.height)*300),(x/cv.width)*2-1,0.7,0.2);
  ripple(x,y,'#6fb3d4');
  callLight.active=false; promptShown='';
  if('speechSynthesis' in window) window.speechSynthesis.cancel();
  speaking=false;
}
function anchorUpdate(){
  if(!anchorActive)return;
  const now=performance.now();
  const since=now-lastTouchT;
  if(since>2500){
    if(!callLight.active){
      callLight.active=true; callLight.t=0;
      promptShown=nextPrompt();
      speak(promptShown); promptIdx++;
      lastPromptT=now;
    }
    callLight.t+=0.02;
    callLight.x=cv.width*(0.5+0.28*Math.sin(callLight.t*1.1));
    callLight.y=cv.height*(0.5+0.24*Math.sin(callLight.t*0.8+1));
    if(Math.floor(callLight.t*10)%20===0) voiceThrottled(330,0);
    if(ZMUSIC.gain) ZMUSIC.gain.gain.rampTo((MOOD_PROFILES[ZMUSIC.mood].vol)+0.12, 2);
    // If they stay away, keep gently offering DIFFERENT statements every ~7s
    // (varied, never the same twice in a row) so it never becomes a silent wait
    // or a repeated loop. The interval breathes a little so it isn't mechanical.
    const gap = 6500 + Math.random()*2500;
    if(now - lastPromptT > gap){
      promptShown=nextPrompt();
      speak(promptShown);
      lastPromptT=now;
    }
  } else {
    if(ZMUSIC.gain) ZMUSIC.gain.gain.rampTo(MOOD_PROFILES[ZMUSIC.mood].vol, 2);
  }
}

// ---- visuals ----
let ripples=[];
function ripple(x,y,color){ ripples.push({x,y,r:0,a:0.6,color}); }
function hexA(hex,a){const n=parseInt(hex.slice(1),16);return 'rgba('+((n>>16)&255)+','+((n>>8)&255)+','+(n&255)+','+a.toFixed(2)+')';}
let pointer={x:0,y:0,down:false};
function drawMusicGlow(){
  const t=performance.now(); const breathe=0.5+0.5*Math.sin(t*0.0007);
  ctx.beginPath(); ctx.arc(cv.width/2,cv.height/2,70+breathe*26,0,7);
  const g=ctx.createRadialGradient(cv.width/2,cv.height/2,10,cv.width/2,cv.height/2,110+breathe*26);
  g.addColorStop(0,'rgba(111,179,212,'+(0.08+breathe*0.08)+')');
  g.addColorStop(1,'rgba(111,179,212,0)'); ctx.fillStyle=g; ctx.fill();
}
function loop(){
  requestAnimationFrame(loop);
  // When a realistic video is showing, clear transparent so it shows through;
  // otherwise paint the dark trail background for the light-only view.
  if(currentScene!=='none' && document.getElementById('calm-video').classList.contains('visible')){
    ctx.clearRect(0,0,cv.width,cv.height);
  } else {
    ctx.fillStyle='rgba(12,19,34,0.22)'; ctx.fillRect(0,0,cv.width,cv.height);
  }
  drawMusicGlow();
  if(mode==='anchor'){
    anchorUpdate();
    if(callLight.active){
      ctx.beginPath(); ctx.arc(callLight.x,callLight.y,30,0,7);
      const g=ctx.createRadialGradient(callLight.x,callLight.y,2,callLight.x,callLight.y,46);
      g.addColorStop(0,'#bfe9ff'); g.addColorStop(1,'rgba(111,179,212,0)'); ctx.fillStyle=g; ctx.fill();
      if(promptShown){ ctx.fillStyle='rgba(232,238,245,0.94)'; ctx.font='300 26px -apple-system,sans-serif';
        ctx.textAlign='center'; ctx.fillText(promptShown, cv.width/2, cv.height*0.20); }
    }
  }
  if(mode==='trace' && pointer.down){ traceMove(pointer.x,pointer.y); ripple(pointer.x,pointer.y,'#6fb3d4'); }
  if(mode==='hum'){ const h=humAnalyze(); if(h) ripple(cv.width/2, cv.height*(1-(h.target-200)/500), '#e0c46f'); }
  if(mode==='mirror'){
    const now=performance.now();
    const delayed=mirrorTrail.find(p=>now-p.t>=500);
    if(pointer.down){ ctx.beginPath();ctx.arc(pointer.x,pointer.y,16,0,7);ctx.fillStyle='rgba(111,179,212,0.8)';ctx.fill(); }
    if(delayed){ ctx.beginPath();ctx.arc(delayed.x,delayed.y,16,0,7);ctx.fillStyle='rgba(224,196,111,0.7)';ctx.fill();
      voiceThrottled(nearestPent(220+(1-delayed.y/cv.height)*440),(delayed.x/cv.width)*2-1); }
  }
  ripples.forEach(r=>{ r.r+=2.5; r.a*=0.96; ctx.beginPath(); ctx.arc(r.x,r.y,r.r,0,7);
    ctx.strokeStyle=hexA(r.color,r.a); ctx.lineWidth=2; ctx.stroke(); });
  ripples=ripples.filter(r=>r.a>0.03);
}

// Realistic video scenes (realism leads; abstract canvas is fallback).
// Videos are served from /scenes/ — run the scene downloader on your machine
// to populate them. If a video can't load, we fall back to the light canvas.
const SCENE_FILES = {
  water:  '/scenes/ocean.mp4',
  clouds: '/scenes/clouds.mp4',
  candle: '/scenes/candle.mp4',
  rain:   '/scenes/rain.mp4',
};
let currentScene = 'none';
function setScene(name){
  currentScene = name;
  document.querySelectorAll('.scene-btn').forEach(b=>b.classList.toggle('active', b.dataset.scene===name));
  const v = document.getElementById('calm-video');
  if(name==='none' || !SCENE_FILES[name]){
    v.classList.remove('visible');
    try{ v.pause(); }catch(e){}
    return;
  }
  // Try the realistic video first
  v.src = SCENE_FILES[name];
  v.classList.remove('visible');
  v.oncanplay = ()=>{ v.classList.add('visible'); try{ v.play(); }catch(e){} };
  v.onerror = ()=>{ // graceful fallback: no video present, keep the light canvas
    v.classList.remove('visible');
    document.getElementById('hint').textContent =
      'Realistic scene not found \u2014 run the scene downloader to add it. Light view active.';
  };
  v.load();
}

function buildModes(){
  const c=document.getElementById('modes');
  MODES.forEach(m=>{
    const b=document.createElement('button');
    b.className='mode-btn'+(m.id==='anchor'?' active':'');
    b.textContent=m.name; b.dataset.id=m.id;
    b.onclick=()=>{ document.querySelectorAll('.mode-btn').forEach(x=>x.classList.remove('active'));
      b.classList.add('active'); setMode(m.id); };
    c.appendChild(b);
  });
}
function setMode(id){
  mode=id;
  const m=MODES.find(x=>x.id===id);
  document.getElementById('modeDesc').textContent=m.desc;
  document.getElementById('hint').textContent=m.desc;
  if(humStream){ humStream.getTracks().forEach(t=>t.stop()); humStream=null; humAnalyser=null; if(humOsc){try{humOsc.stop();}catch(e){}humOsc=null;} }
  traceRelease();
  if(id!=='anchor') stopAnchor();
  if(id==='anchor') startAnchor();
  if(id==='hum') startHum();
  if(id==='mirror') mirrorTrail=[];
}
async function labStart(){
  document.getElementById('gate').style.display='none';
  document.getElementById('musicbar').style.display='flex';
  document.getElementById('scene-bar').style.display='flex';
  await Tone.start();
  AC=Tone.getContext().rawContext; started=true;
  startMusic('calm');
  buildModes(); setMode('anchor');
  if('speechSynthesis' in window){ window.speechSynthesis.getVoices(); }
  loop();
}
function pos(e){ const t=e.touches?e.touches[0]:e; const r=cv.getBoundingClientRect(); return {x:t.clientX-r.left,y:t.clientY-r.top}; }
function down(e){ if(!AC)return; const p=pos(e); pointer={x:p.x,y:p.y,down:true};
  if(mode==='anchor') anchorTouch(p.x,p.y);
  if(mode==='call') callTap(p.x,p.y);
  if(mode==='mirror') mirrorMove(p.x,p.y);
  e.preventDefault();
}
function move(e){ if(!pointer.down)return; const p=pos(e); pointer.x=p.x; pointer.y=p.y;
  if(mode==='anchor') anchorTouch(p.x,p.y);
  if(mode==='mirror') mirrorMove(p.x,p.y);
  e.preventDefault();
}
function up(){ pointer.down=false; if(mode==='trace') traceRelease(); }
cv.addEventListener('mousedown',down); cv.addEventListener('mousemove',move); window.addEventListener('mouseup',up);
cv.addEventListener('touchstart',down,{passive:false}); cv.addEventListener('touchmove',move,{passive:false}); window.addEventListener('touchend',up);
</script>
</body></html>"""
