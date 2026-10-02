// CyDecompilator export script for Ghidra headless.
//
// Arguments: <outputDir> <mode> <maxDecompile> <timeoutSeconds> [addresses]
//   mode "all"       : write program.json (functions, call graph, strings, imports,
//                      sections) and decompile up to maxDecompile functions into code/.
//   mode "decompile" : decompile only the comma separated entry addresses in [addresses].
//
// Output is plain JSON written by hand so the script depends on nothing but Ghidra.
// Progress lines "CYPROGRESS done total" are parsed by the Tool.
//@category CyDecompilator

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolIterator;

public class CyExport extends GhidraScript {

    private static String json(String value) {
        if (value == null) return "null";
        StringBuilder out = new StringBuilder(value.length() + 16);
        out.append('"');
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            switch (c) {
                case '"': out.append("\\\""); break;
                case '\\': out.append("\\\\"); break;
                case '\n': out.append("\\n"); break;
                case '\r': out.append("\\r"); break;
                case '\t': out.append("\\t"); break;
                default:
                    if (c < 0x20) out.append(String.format("\\u%04x", (int) c));
                    else out.append(c);
            }
        }
        out.append('"');
        return out.toString();
    }

    private static String hex(Address address) {
        return "0x" + Long.toHexString(address.getOffset());
    }

    private void write(File file, String text) throws Exception {
        file.getParentFile().mkdirs();
        try (Writer writer = new OutputStreamWriter(new FileOutputStream(file), StandardCharsets.UTF_8)) {
            writer.write(text);
        }
    }

    private DecompInterface decompiler() {
        DecompInterface ifc = new DecompInterface();
        DecompileOptions options = new DecompileOptions();
        ifc.setOptions(options);
        ifc.toggleCCode(true);
        ifc.toggleSyntaxTree(false);
        ifc.setSimplificationStyle("decompile");
        ifc.openProgram(currentProgram);
        return ifc;
    }

    private boolean decompileOne(DecompInterface ifc, Function function, File codeDir, int timeout) throws Exception {
        DecompileResults results = ifc.decompileFunction(function, timeout, monitor);
        String name = hex(function.getEntryPoint());
        if (results != null && results.decompileCompleted() && results.getDecompiledFunction() != null) {
            write(new File(codeDir, name + ".c"), results.getDecompiledFunction().getC());
            return true;
        }
        String error = results == null ? "no result" : results.getErrorMessage();
        write(new File(codeDir, name + ".error.txt"), error == null ? "unknown error" : error);
        return false;
    }

    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        File out = new File(args[0]);
        String mode = args.length > 1 ? args[1] : "all";
        int maxDecompile = args.length > 2 ? Integer.parseInt(args[2]) : 0;
        int timeout = args.length > 3 ? Integer.parseInt(args[3]) : 60;
        File codeDir = new File(out, "code");
        codeDir.mkdirs();

        if (mode.equals("decompile")) {
            DecompInterface ifc = decompiler();
            try {
                String[] targets = args.length > 4 ? args[4].split(",") : new String[0];
                for (String target : targets) {
                    if (target.isEmpty()) continue;
                    Address address = toAddr(target);
                    Function function = getFunctionAt(address);
                    if (function == null) function = getFunctionContaining(address);
                    if (function == null) {
                        write(new File(codeDir, target + ".error.txt"), "no function at " + target);
                        continue;
                    }
                    decompileOne(ifc, function, codeDir, timeout);
                }
            } finally {
                ifc.dispose();
            }
            return;
        }

        StringBuilder sb = new StringBuilder(1 << 20);
        sb.append("{\n\"program\": {");
        sb.append("\"name\": ").append(json(currentProgram.getName()));
        sb.append(", \"language\": ").append(json(currentProgram.getLanguageID().getIdAsString()));
        sb.append(", \"compiler\": ").append(json(currentProgram.getCompilerSpec().getCompilerSpecID().getIdAsString()));
        sb.append(", \"imageBase\": ").append(json(hex(currentProgram.getImageBase())));
        sb.append(", \"pointerSize\": ").append(currentProgram.getDefaultPointerSize());
        sb.append(", \"executableFormat\": ").append(json(currentProgram.getExecutableFormat()));
        sb.append("},\n");

        sb.append("\"sections\": [");
        boolean first = true;
        for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
            if (!first) sb.append(",");
            first = false;
            sb.append("\n{\"name\": ").append(json(block.getName()))
              .append(", \"address\": ").append(json(hex(block.getStart())))
              .append(", \"size\": ").append(block.getSize())
              .append(", \"executable\": ").append(block.isExecute())
              .append(", \"writable\": ").append(block.isWrite()).append("}");
        }
        sb.append("],\n");

        List<Function> functions = new ArrayList<>();
        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        while (iterator.hasNext()) functions.add(iterator.next());

        sb.append("\"functions\": [");
        first = true;
        int index = 0;
        for (Function function : functions) {
            if (monitor.isCancelled()) break;
            if (!first) sb.append(",");
            first = false;
            sb.append("\n{\"id\": ").append(json(hex(function.getEntryPoint())))
              .append(", \"name\": ").append(json(function.getName(true)))
              .append(", \"address\": ").append(json(hex(function.getEntryPoint())))
              .append(", \"size\": ").append(function.getBody().getNumAddresses())
              .append(", \"kind\": \"function\"")
              .append(", \"signature\": ").append(json(function.getPrototypeString(false, false)))
              .append(", \"callingConvention\": ").append(json(function.getCallingConventionName()))
              .append(", \"thunk\": ").append(function.isThunk())
              .append(", \"external\": ").append(function.isExternal());
            Set<Function> called = function.getCalledFunctions(monitor);
            sb.append(", \"callees\": [");
            boolean firstCallee = true;
            List<String> imports = new ArrayList<>();
            for (Function callee : called) {
                if (callee.isExternal() || callee.isThunk()) {
                    imports.add(callee.getName(true));
                }
                if (callee.isExternal()) continue;
                if (!firstCallee) sb.append(",");
                firstCallee = false;
                sb.append(json(hex(callee.getEntryPoint())));
            }
            sb.append("], \"imports\": [");
            for (int i = 0; i < imports.size(); i++) {
                if (i > 0) sb.append(",");
                sb.append(json(imports.get(i)));
            }
            sb.append("], \"callers\": [");
            boolean firstCaller = true;
            for (Function caller : function.getCallingFunctions(monitor)) {
                if (!firstCaller) sb.append(",");
                firstCaller = false;
                sb.append(json(hex(caller.getEntryPoint())));
            }
            sb.append("]}");
            index++;
            if (index % 500 == 0) println("CYPROGRESS list " + index + " " + functions.size());
        }
        sb.append("],\n");

        sb.append("\"imports\": [");
        first = true;
        SymbolIterator externals = currentProgram.getSymbolTable().getExternalSymbols();
        while (externals.hasNext()) {
            Symbol symbol = externals.next();
            if (!first) sb.append(",");
            first = false;
            String library = symbol.getParentNamespace() == null ? "" : symbol.getParentNamespace().getName();
            sb.append("\n{\"library\": ").append(json(library))
              .append(", \"name\": ").append(json(symbol.getName())).append("}");
        }
        sb.append("],\n");

        sb.append("\"strings\": [");
        first = true;
        int strings = 0;
        DataIterator data = currentProgram.getListing().getDefinedData(true);
        while (data.hasNext() && strings < 60000) {
            Data item = data.next();
            if (!item.hasStringValue()) continue;
            Object value = item.getValue();
            if (value == null) continue;
            String text = value.toString();
            if (text.length() > 400) text = text.substring(0, 400);
            if (!first) sb.append(",");
            first = false;
            sb.append("\n{\"address\": ").append(json(hex(item.getAddress())))
              .append(", \"text\": ").append(json(text)).append("}");
            strings++;
        }
        sb.append("]\n}\n");
        write(new File(out, "program.json"), sb.toString());
        println("CYPROGRESS listed " + functions.size() + " " + functions.size());

        if (maxDecompile > 0) {
            DecompInterface ifc = decompiler();
            try {
                int done = 0;
                int total = 0;
                for (Function function : functions) {
                    if (!function.isExternal() && !function.isThunk()) total++;
                }
                total = Math.min(total, maxDecompile);
                for (Function function : functions) {
                    if (monitor.isCancelled() || done >= maxDecompile) break;
                    if (function.isExternal() || function.isThunk()) continue;
                    decompileOne(ifc, function, codeDir, timeout);
                    done++;
                    if (done % 20 == 0 || done == total) println("CYPROGRESS decompile " + done + " " + total);
                }
            } finally {
                ifc.dispose();
            }
        }
    }
}
