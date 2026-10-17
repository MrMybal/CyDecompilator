'use strict';
// No source is executed. Syntax validation and transpilation use the private parser.
const fs=require('fs'),path=require('path'),ts=require(process.argv[2]);
const input=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
let failed=false;
for(const name of input.files) {
  if(/\.html?$/i.test(name)) {
    const file=path.join(input.directory,name);
    fs.writeFileSync(file,fs.readFileSync(file,'utf8').replace(/(\bsrc\s*=\s*["'][^"']+)\.(?:ts|tsx|jsx)(["'])/gi,'$1.js$2'));
    continue;
  }
  if(!/\.(?:[cm]?js|jsx|tsx?)$/i.test(name) || /\.d\.ts$/i.test(name))continue;
  const file=path.join(input.directory,name),source=fs.readFileSync(file,'utf8');
  const parsed=ts.createSourceFile(name,source,ts.ScriptTarget.Latest,true);
  for(const error of parsed.parseDiagnostics || []) {
    const pos=parsed.getLineAndCharacterOfPosition(error.start || 0);
    process.stderr.write(`${name}(${pos.line+1},${pos.character+1}): error TS${error.code}: ${ts.flattenDiagnosticMessageText(error.messageText,' ')}\n`);
    failed=true;
  }
  if(failed)continue;
  if(/\.(?:jsx|tsx?)$/i.test(name)) {
    const destination=name.replace(/\.(?:jsx|tsx?)$/i,'.js');
    if(input.files.some(n=>n.toLowerCase()===destination.toLowerCase())) {
      process.stderr.write(`${name}(1,1): error TS5056: Reconstructed output conflicts with ${destination}; select a project build script.\n`);
      failed=true;continue;
    }
    const packageFile=path.join(input.directory,'package.json');
    const esm=fs.existsSync(packageFile) && JSON.parse(fs.readFileSync(packageFile,'utf8')).type==='module';
    const transformed=ts.transpileModule(source,{fileName:name,reportDiagnostics:true,compilerOptions:{
      target:ts.ScriptTarget.ES2022,module:esm?ts.ModuleKind.ES2022:ts.ModuleKind.CommonJS,
      jsx:ts.JsxEmit.ReactJSX,sourceMap:true,inlineSources:true,rewriteRelativeImportExtensions:true}});
    for(const error of transformed.diagnostics || []) {
      process.stderr.write(`${name}: error TS${error.code}: ${ts.flattenDiagnosticMessageText(error.messageText,' ')}\n`);failed=true;
    }
    const output=file.replace(/\.(?:jsx|tsx?)$/i,'.js');
    fs.writeFileSync(output,transformed.outputText);if(transformed.sourceMapText)fs.writeFileSync(output+'.map',transformed.sourceMapText);
  } else fs.writeFileSync(file,ts.createPrinter({newLine:ts.NewLineKind.LineFeed,removeComments:false}).printFile(parsed));
}
const packageFile=path.join(input.directory,'package.json');
if(fs.existsSync(packageFile)) {
  const metadata=JSON.parse(fs.readFileSync(packageFile,'utf8'));
  if(/\.(?:tsx?|jsx)$/i.test(metadata.main || ''))metadata.main=metadata.main.replace(/\.(?:tsx?|jsx)$/i,'.js');
  fs.writeFileSync(packageFile,JSON.stringify(metadata,null,2)+'\n');
}
process.stdout.write(failed?'JavaScript build failed.\n':'Syntax checked; TypeScript/JSX transpiled. Type checking was not performed.\n');
process.exitCode=failed?1:0;
