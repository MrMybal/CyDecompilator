// Export analysis pseudocode; native runtime and reconstruction remain separate.
// @category XboxNative
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

public class ExportXboxFunctions extends GhidraScript {
    @Override public void run() throws Exception {
        Path output=Path.of(getScriptArgs()[0]);
        Files.createDirectory(output);
        DecompInterface decompiler=new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) throw new IllegalStateException("Cannot open decompiler");
        int exported=0, failed=0;
        try {
            FunctionIterator functions=currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext() && !monitor.isCancelled()) {
                Function function=functions.next();
                if (function.isExternal()) continue;
                DecompileResults result=decompiler.decompileFunction(function,30,monitor);
                String address=function.getEntryPoint().toString();
                if (result.decompileCompleted()) {
                    Files.writeString(output.resolve("function_"+address+".c"),
                        "/* Xbox analysis pseudocode; native imports/runtime unresolved. */\n"+result.getDecompiledFunction().getC(),StandardCharsets.UTF_8);
                    exported++;
                } else {
                    Files.writeString(output.resolve("function_"+address+".error.txt"),result.getErrorMessage(),StandardCharsets.UTF_8);
                    failed++;
                }
            }
            Files.writeString(output.resolve("export.json"),"{\"schema_version\":1,\"exported_functions\":"+exported+
                ",\"failed_functions\":"+failed+",\"native_game_ready\":false}\n",StandardCharsets.UTF_8);
        } finally { decompiler.dispose(); }
    }
}
