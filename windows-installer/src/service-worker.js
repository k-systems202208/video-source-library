const CACHE_NAME='video-library-shell-v3';
const SHELL=['/','/manifest.webmanifest','/offline.html','/icon.svg'];
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE_NAME).then(cache=>cache.addAll(SHELL)));self.skipWaiting();});
self.addEventListener('activate',event=>{event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE_NAME).map(key=>caches.delete(key)))));self.clients.claim();});
self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET')return;
  const url=new URL(request.url);
  if(url.origin!==self.location.origin)return;
  if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/video/')||url.pathname.startsWith('/subtitle/'))return;
  if(request.mode==='navigate'){
    event.respondWith(fetch(request).then(response=>response).catch(()=>caches.match('/offline.html')));
    return;
  }
  if(!SHELL.includes(url.pathname))return;
  event.respondWith(caches.match(request).then(cached=>cached||fetch(request)));
});
