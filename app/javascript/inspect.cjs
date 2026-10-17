// Inert AST analysis: require only our private compiler, never an inspected module.
'use strict';
const fs = require('fs');
const ts = require(process.argv[2]);
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const results = [];
let totalFacts = 0;
for (const file of input.files) {
  if (totalFacts>=60000) { results.push({path:file.path,facts:[],unknowns:[{code:'graph-node-limit'}]}); continue; }
  const text = fs.readFileSync(file.absolute, 'utf8');
  const sf = ts.createSourceFile(file.path, text, ts.ScriptTarget.Latest, true);
  const facts = [], unknowns = [], aliases = new Map(), shadowCache = new Map();
  const pos = n => { const p = sf.getLineAndCharacterOfPosition(n.getStart(sf));
    return {line:p.line+1, column:p.character+1, start:n.getStart(sf), end:n.end}; };
  const add = (kind, label, n, owner, details={}) => {
    const key = facts.length; facts.push({key, kind, label, ...pos(n), owner, details}); return key; };
  const literal = n => n && (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n)) ? n.text : null;
  const expr = n => n ? n.getText(sf).slice(0,400) : '';
  const binding = (n, mod) => {
    if (!n) return;
    if (ts.isObjectBindingPattern(n)) for (const b of n.elements)
      aliases.set(b.name.getText(sf), mod + '.' + (b.propertyName || b.name).getText(sf));
    else if (ts.isIdentifier(n)) aliases.set(n.text, mod);
  };
  // Bindings are only a candidate; shadowed receivers are never attributed to Electron.
  const shadowed = name => {
    if (shadowCache.has(name)) return shadowCache.get(name);
    let count = 0;
    function walk(n) {
      if ((ts.isVariableDeclaration(n) || ts.isParameter(n) || ts.isFunctionDeclaration(n)) && n.name) {
        if (ts.isIdentifier(n.name) && n.name.text === name) count++;
        if (ts.isObjectBindingPattern(n.name)) for (const e of n.name.elements)
          if (e.name.getText(sf) === name) count++;
      }
      if (ts.isImportSpecifier(n) && n.name.text === name) count++;
      if (ts.isNamespaceImport(n) && n.name.text === name) count++;
      if (ts.isImportClause(n) && n.name && n.name.text === name) count++;
      ts.forEachChild(n, walk);
    } walk(sf); shadowCache.set(name,count>1); return count > 1;
  };
  function collect(n) {
    if (ts.isImportDeclaration(n) && literal(n.moduleSpecifier)) {
      const mod = literal(n.moduleSpecifier), clause = n.importClause;
      if (clause && clause.name) aliases.set(clause.name.text, mod);
      if (clause && clause.namedBindings) {
        if (ts.isNamespaceImport(clause.namedBindings)) aliases.set(clause.namedBindings.name.text, mod);
        else for (const el of clause.namedBindings.elements)
          aliases.set(el.name.text, mod + '.' + (el.propertyName || el.name).text);
      }
    }
    if (ts.isVariableDeclaration(n) && n.initializer && ts.isCallExpression(n.initializer) &&
        expr(n.initializer.expression) === 'require') binding(n.name, literal(n.initializer.arguments[0]) || '?');
    if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer && ts.isNewExpression(n.initializer)) {
      const constructor=expr(n.initializer.expression), receiver=constructor.split('.')[0];
      if (aliases.get(receiver)+constructor.slice(receiver.length)==='electron.BrowserWindow' && !shadowed(receiver))
        aliases.set(n.name.text,'electron.window');
    }
    ts.forEachChild(n, collect);
  } collect(sf);
  function pathValue(n) {
    const lit = literal(n); if (lit !== null) return lit;
    if (n && ts.isCallExpression(n) && /^(path\.)?(join|resolve)$/.test(expr(n.expression))) {
      const args = n.arguments.map(a => expr(a) === '__dirname' ? '.' : literal(a));
      if (args.every(a => a !== null)) return args.join('/');
    } return null;
  }
  function visit(n, owner=null) {
    if (facts.length >= Math.min(10000,60000-totalFacts)) return;
    let next = owner;
    if (ts.isFunctionLike(n) && n.body) {
      const name = n.name ? expr(n.name) : n.parent && ts.isVariableDeclaration(n.parent) ? expr(n.parent.name) : '<callback>';
      next = add('function', name, n, owner, {async:!!n.modifiers?.some(m=>m.kind===ts.SyntaxKind.AsyncKeyword)});
    }
    if (ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) {
      if (n.moduleSpecifier) add('module', literal(n.moduleSpecifier) || expr(n.moduleSpecifier), n, next,
                                {value:literal(n.moduleSpecifier), syntax:ts.isImportDeclaration(n)?'import':'export'});
    }
    if (ts.isCallExpression(n) || ts.isNewExpression(n)) {
      const callee = expr(n.expression), args = n.arguments || [];
      const receiver = callee.split('.')[0], imported = aliases.get(receiver);
      const qualified = imported && !shadowed(receiver) ? imported + callee.slice(receiver.length) : '';
      if (imported && shadowed(receiver)) unknowns.push({code:'ambiguous-receiver-binding', receiver, ...pos(n)});
      const call = add('call', callee, n, next, {callee, qualified,
          identifiers:args.filter(a=>ts.isIdentifier(a)).map(a=>a.text)});
      if (ts.isPropertyAccessExpression(n.expression) && n.expression.name.text==='addEventListener' &&
          ts.isCallExpression(n.expression.expression) && expr(n.expression.expression.expression)==='document.getElementById') {
        const value=literal(n.expression.expression.arguments[0]);
        add('ui-binding',value || expr(n.expression.expression.arguments[0]),n,next,
            {value,event:literal(args[0]),callback:args[1] && ts.isIdentifier(args[1])?args[1].text:null,call,candidate:true});
      }
      if (callee === 'require' || n.expression.kind === ts.SyntaxKind.ImportKeyword) {
        const value = literal(args[0]); add('module', value || expr(args[0]), n, next, {value, syntax:callee});
        if (value === null) unknowns.push({code:'dynamic-module', ...pos(n)});
      }
      if (/^electron\.ipcMain\.(handle|handleOnce|on|once)$/.test(qualified) ||
          /^electron\.ipcRenderer\.(on|once|invoke|send|sendSync)$/.test(qualified) ||
          qualified==='electron.window.webContents.send') {
        const value = literal(args[0]);
        const handler=/ipcMain/.test(qualified) || /^electron\.ipcRenderer\.(on|once)$/.test(qualified);
        const direction=/ipcMain/.test(qualified) || /^electron\.ipcRenderer\.(invoke|send|sendSync)$/.test(qualified) ? 'renderer-to-main':'main-to-renderer';
        add('ipc', value === null ? expr(args[0]) : value, n, next, {value, role:handler?'handler':'sender', direction, qualified, call});
        if (value === null) unknowns.push({code:'dynamic-ipc', ...pos(n)});
      }
      if (qualified === 'electron.contextBridge.exposeInMainWorld') {
        const methods=args[1] && ts.isObjectLiteralExpression(args[1]) ? args[1].properties
          .filter(p=>p.name && (ts.isPropertyAssignment(p)||ts.isMethodDeclaration(p)))
          .map(p=>expr(p.name).replace(/['"]/g,'')) : [];
        add('bridge', literal(args[0]) || expr(args[0]), n, next, {value:literal(args[0]), methods, call});
      }
      if (qualified === 'electron.BrowserWindow') {
        add('window', callee, n, next, {call});
        const inspectOptions = object => {
          if (!object || !ts.isObjectLiteralExpression(object)) return;
          for (const p of object.properties) if (ts.isPropertyAssignment(p)) {
            const name = expr(p.name).replace(/['"]/g,'');
            if (name === 'preload') { const value=pathValue(p.initializer);
              add('preload', value || expr(p.initializer), p, next, {value, call});
              if (value===null) unknowns.push({code:'dynamic-preload', ...pos(p)}); }
            if (['contextIsolation','nodeIntegration','sandbox'].includes(name))
              add('window-option', name, p, next, {value:expr(p.initializer), call});
            inspectOptions(p.initializer);
          }
        }; inspectOptions(args[0]);
      }
      if (/\.(loadFile|loadURL)$/.test(callee)) add('resource', pathValue(args[0]) || expr(args[0]), n, next,
          {value:pathValue(args[0]), call, candidate:true});
      if (/^(fetch|axios\.(get|post|put|delete|patch)|.*\.(get|post|put|delete|patch|use|route))$/.test(callee)) {
        const value = literal(args[0]);
        if (value !== null) add(callee==='fetch'||callee.startsWith('axios.')?'endpoint':'route', value, n, next,
                               {value, method:callee, candidate:true, call});
        else unknowns.push({code:'dynamic-endpoint', ...pos(n)});
      }
      // Literal text in call arguments remains searchable with its containing function.
      next = call;
    }
    if (ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n))
      if (n.text.trim()) add('literal', n.text.slice(0,600), n, next, {value:n.text.slice(0,600)});
    ts.forEachChild(n, child=>visit(child,next));
  } visit(sf);
  const scanner = ts.createScanner(ts.ScriptTarget.Latest,false,ts.LanguageVariant.Standard,text);
  for(let token=scanner.scan();token!==ts.SyntaxKind.EndOfFileToken;token=scanner.scan()) {
    if(token===ts.SyntaxKind.SingleLineCommentTrivia || token===ts.SyntaxKind.MultiLineCommentTrivia) {
      const match=/[#@]\s*sourceMappingURL\s*=\s*([^\s*]+)/.exec(scanner.getTokenText());
      if(match) { const p=sf.getLineAndCharacterOfPosition(scanner.getTokenPos());
        facts.push({key:facts.length,kind:'source-map',label:match[1].slice(0,600),line:p.line+1,column:p.character+1,
                    start:scanner.getTokenPos(),end:scanner.getTextPos(),owner:null,details:{value:match[1]}}); }
    }
  }
  if (facts.length>=10000) unknowns.push({code:'ast-fact-limit'});
  for (const d of sf.parseDiagnostics) unknowns.push({code:'syntax-error',
    message:ts.flattenDiagnosticMessageText(d.messageText,'\n'), start:d.start});
  totalFacts += facts.length;
  results.push({path:file.path, facts, unknowns});
}
fs.writeFileSync(process.argv[4], JSON.stringify({parserVersion:ts.version, results}));
