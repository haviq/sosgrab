
(function(){
  var $=function(id){return document.getElementById(id)};
  function fmtSize(b){ if(!b) return ''; var u=['B','KB','MB','GB'],i=0; while(b>=1024&&i<3){b/=1024;i++} return ' · '+(b>=10?Math.round(b):b.toFixed(1))+' '+u[i]; }
  function fmtDur(s){ if(!s) return ''; var m=Math.floor(s/60),x=Math.round(s%60); return m+':'+(x<10?'0':'')+x; }
  document.getElementById('f').addEventListener('submit', function(e){
    e.preventDefault();
    var url=$('url').value.trim();
    var msg=$('msg'), btn=$('go');
    msg.className='msg'; msg.innerHTML='';
    if(!url){ msg.textContent='Paste a link first.'; return; }
    // soft pre-check: platform vs cookie keys (non-blocking warning)
    var hint=$('cookieHint'), ck=$('cookies').value.trim();
    hint.textContent='';
    var needs={facebook:['c_user','xs'],'fb.watch':['c_user','xs'],'instagram':['sessionid'],'tiktok':['sessionid']};
    for(var pat in needs){
      if(new RegExp(pat,'i').test(url) && ck){
        var missing=needs[pat].filter(function(k){return ck.toLowerCase().indexOf(k.toLowerCase()+'=')<0;});
        if(missing.length){ hint.style.color='var(--err)'; hint.textContent='Cookie looks incomplete for this platform — missing: '+missing.join(', ')+'. It may still fail.'; }
      }
    }
    btn.disabled=true; msg.innerHTML='<span class="spin"></span>Extracting links...';
    fetch('/api/resolve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:url, cookies:document.getElementById('cookies').value.trim()})})
      .then(function(r){return r.json().then(function(j){return{ok:r.ok,j:j}})})
      .then(function(res){
        btn.disabled=false;
        if(!res.ok){ msg.className='msg err'; msg.textContent=(res.j&&res.j.detail)||'Extraction failed.'; return; }
        msg.textContent='';
        var d=res.j;
        $('card').style.display='block';
        $('card').scrollIntoView({behavior:'smooth',block:'start'});
        if(d.thumbnail){ $('thumb').src=d.thumbnail; $('thumb').style.display='block'; } else $('thumb').style.display='none';
        $('pf').textContent=d.platform + (d.duration?(' · '+fmtDur(d.duration)):'');
        $('title').textContent=d.title;
        $('up').textContent=d.uploader?('by '+d.uploader):'';
        var h='';
        var videoOnly=null, audioOnly=null, combined=false;
        d.formats.forEach(function(f){
          if(f.video && f.has_sound) combined=true;
          if(f.video && !f.has_sound && !videoOnly) videoOnly=f;
          if(!f.video && !audioOnly) audioOnly=f;
          var icon = (f.video && f.has_sound) ? '🔊' : (f.video ? '🔇' : '♪');
          h+='<a class="dl'+(f.video?'':' audio')+'" href="'+f.url+'" target="_blank" rel="noopener">'+
             '<span class="q">'+icon+' '+f.label+'</span>'+
             '<span class="x">'+(f.ext||'').toUpperCase()+fmtSize(f.filesize)+' ↧</span></a>';
        });
        $('links').innerHTML=h||'<p style="color:var(--muted)">No downloadable formats found.</p>';
        // show merge button only when the platform gave separate streams
        var mb=$('mergeBox');
        if(!combined && videoOnly && audioOnly){
          mb.style.display='flex';
          $('mergeMsg').textContent='';
          setupMerge(videoOnly, audioOnly);
        } else { mb.style.display='none'; }
      })
      .catch(function(){ btn.disabled=false; msg.className='msg err'; msg.textContent='Could not reach the service.'; });
  });
  // ---- in-browser merge (ffmpeg.wasm) for platforms that split video/audio ----
  var mergeReady=null;
  function setupMerge(videoOnly, audioOnly){
    var btn=$('mergeBtn'), mmsg=$('mergeMsg');
    btn.onclick=function(){
      if(!mergeReady){
        mmsg.innerHTML='<span class="spin"></span>Loading merger (first time ~10 MB)...';
        var s1=document.createElement('script'); s1.src='/static/ffmpeg/ffmpeg.js';
        s1.onload=function(){
          try{
            var ff=new FFmpegWASM.FFmpeg();
            ff.on('progress', function(p){ mmsg.textContent='Merging... '+Math.round((p.progress||0)*100)+'%'; });
            ff.load({coreURL:'/static/ffmpeg/ffmpeg-core.js',
                     wasmURL:'/static/ffmpeg/ffmpeg-core.wasm',
                     classWorkerURL:'/static/ffmpeg/814.ffmpeg.js'})
              .then(function(){ mergeReady=ff; doMerge(); })
              .catch(function(e){ mmsg.className='msg err'; mmsg.textContent='Merger failed to load: '+(e&&e.message||e); });
          }catch(e){ mmsg.className='msg err'; mmsg.textContent='Merger failed: '+(e&&e.message||e); }
        };
        s1.onerror=function(){ mmsg.className='msg err'; mmsg.textContent='Could not load the merger (network).'; };
        document.head.appendChild(s1);
      } else { doMerge(); }
      function doMerge(){
        mmsg.className='msg'; mmsg.textContent='Downloading video & audio...';
        btn.disabled=true;
        Promise.all([
          fetch(videoOnly.url).then(function(r){ if(!r.ok) throw new Error('video fetch '+r.status); return r.arrayBuffer(); }),
          fetch(audioOnly.url).then(function(r){ if(!r.ok) throw new Error('audio fetch '+r.status); return r.arrayBuffer(); })
        ]).then(function(bufs){
          mmsg.textContent='Merging (fast copy, no re-encode)...';
          var ff=mergeReady;
          return Promise.all([
            ff.writeFile('v.mp4', new Uint8Array(bufs[0])),
            ff.writeFile('a.m4a', new Uint8Array(bufs[1]))
          ]).then(function(){ return ff.exec(['-i','v.mp4','-i','a.m4a','-c','copy','-movflags','faststart','out.mp4']); })
            .then(function(){ return ff.readFile('out.mp4'); });
        }).then(function(data){
          var blob=new Blob([data], {type:'video/mp4'});
          var a=document.createElement('a');
          a.href=URL.createObjectURL(blob);
          a.download=(document.getElementById('title').textContent||'sosgrab')+'.mp4';
          document.body.appendChild(a); a.click(); a.remove();
          mmsg.textContent='✅ Merged! Check your downloads.';
          btn.disabled=false;
        }).catch(function(e){
          mmsg.className='msg err';
          mmsg.textContent='Merge failed: '+(e&&e.message||e)+'. (Some platforms block browser downloads of their CDN files — use the two links above instead.)';
          btn.disabled=false;
        });
      }
    };
  }
})();
