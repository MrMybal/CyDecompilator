'use strict';
// Preview a built web tree on loopback, with no directory listings or parent traversal.
const http=require('http'),fs=require('fs'),path=require('path');
const root=fs.realpathSync(process.argv[2]),port=Number(process.argv[3] || 0);
const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.png':'image/png','.svg':'image/svg+xml'};
http.createServer((req,res)=>{
  let relative;try{relative=decodeURIComponent(new URL(req.url,'http://localhost').pathname);}catch{res.writeHead(400);return res.end();}
  const file=path.resolve(root,'.'+relative+(relative.endsWith('/')?'index.html':''));
  try {
    const real=fs.realpathSync(file);
    if(!real.startsWith(root+path.sep) || !fs.statSync(real).isFile())throw Error('Outside preview');
    res.writeHead(200,{'Content-Type':types[path.extname(real)] || 'application/octet-stream'});fs.createReadStream(real).pipe(res);
  }catch{res.writeHead(404);res.end();}
}).listen(port,'127.0.0.1',function(){process.stdout.write('Preview: http://127.0.0.1:'+this.address().port+'/\n');});
