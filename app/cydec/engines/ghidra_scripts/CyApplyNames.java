// CyDecompilator pre-analysis script: apply debug-symbol names before Ghidra analyses the program.
//
// Argument: path of a UTF-8 file with one "address<TAB>kind<TAB>name" line per symbol
// (kind f = function, d = data). Functions are disassembled and created at their start so the
// analysis and the decompiler use the real names (Ghidra's demangler expands MSVC names).
//@category CyDecompilator

import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.app.util.NamespaceUtils;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;

public class CyApplyNames extends GhidraScript {
    @Override
    protected void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) return;
        int functions = 0, labels = 0, failed = 0;
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(new FileInputStream(args[0]), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (monitor.isCancelled()) break;
                String[] parts = line.split("\t", 3);
                if (parts.length < 3) continue;
                try {
                    Address address = toAddr(parts[0]);
                    MemoryBlock block = currentProgram.getMemory().getBlock(address);
                    if (block == null) { failed++; continue; }
                    // "A::B::name" -> name in namespace A::B (created as needed).
                    String full = parts[2];
                    int split = full.lastIndexOf("::");
                    String name = split >= 0 ? full.substring(split + 2) : full;
                    Namespace namespace = currentProgram.getGlobalNamespace();
                    if (split > 0) {
                        namespace = NamespaceUtils.createNamespaceHierarchy(full.substring(0, split), null,
                                                                            currentProgram, SourceType.IMPORTED);
                    }
                    if (parts[1].equals("f") && block.isExecute()) {
                        Function function = getFunctionAt(address);
                        if (function == null) {
                            disassemble(address);
                            function = createFunction(address, name);
                        }
                        if (function != null) {
                            function.setName(name, SourceType.IMPORTED);
                            if (split > 0) function.setParentNamespace(namespace);
                            functions++;
                        } else {
                            currentProgram.getSymbolTable().createLabel(address, name, namespace, SourceType.IMPORTED);
                            labels++;
                        }
                    } else {
                        currentProgram.getSymbolTable().createLabel(address, name, namespace, SourceType.IMPORTED);
                        labels++;
                    }
                } catch (Exception e) {
                    failed++;
                }
            }
        }
        println("CYSYMBOLS functions=" + functions + " labels=" + labels + " failed=" + failed);
    }
}
