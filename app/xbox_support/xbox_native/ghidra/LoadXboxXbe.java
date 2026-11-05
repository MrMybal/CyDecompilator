// Map a validated original-Xbox XBE into an x86:LE:32 program before analysis.
// @category XboxNative
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;
import java.io.ByteArrayInputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Path;

public class LoadXboxXbe extends GhidraScript {
    private static long u32(ByteBuffer b, int offset) { return Integer.toUnsignedLong(b.getInt(offset)); }
    @Override public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 1) throw new IllegalArgumentException("Expected validated XBE input path");
        byte[] data = Files.readAllBytes(Path.of(args[0]));
        if (data.length < 0x178 || data[0]!='X' || data[1]!='B' || data[2]!='E' || data[3]!='H')
            throw new IllegalArgumentException("Not XBEH");
        ByteBuffer b = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
        long base=u32(b,0x104), headers=u32(b,0x108), count=u32(b,0x11c), table=u32(b,0x120)-base;
        if (headers>data.length || count>4096 || table<0 || table+count*56>headers)
            throw new IllegalArgumentException("Invalid section table");
        Memory memory = currentProgram.getMemory();
        for (MemoryBlock block : memory.getBlocks()) memory.removeBlock(block, monitor);
        MemoryBlock header = memory.createInitializedBlock("XBE.headers", toAddr(base),
            new ByteArrayInputStream(data,0,(int)headers), headers, monitor, false);
        header.setRead(true); header.setWrite(false); header.setExecute(false);
        for (int i=0;i<count;i++) {
            int o=(int)table+i*56;
            long flags=u32(b,o), va=u32(b,o+4), virtual=u32(b,o+8), raw=u32(b,o+12), size=u32(b,o+16);
            if (raw+size>data.length || size>virtual || virtual>512L*1024*1024)
                throw new IllegalArgumentException("Invalid section extent");
            if (size>0) {
                MemoryBlock block=memory.createInitializedBlock("XBE.section."+i, toAddr(va),
                    new ByteArrayInputStream(data,(int)raw,(int)size), size, monitor, false);
                block.setRead(true); block.setWrite((flags&1)!=0); block.setExecute((flags&4)!=0);
            }
            if (virtual>size) {
                MemoryBlock zero=memory.createInitializedBlock("XBE.zero."+i, toAddr(va+size), virtual-size, (byte)0, monitor, false);
                zero.setRead(true); zero.setWrite((flags&1)!=0); zero.setExecute((flags&4)!=0);
            }
        }
        long encoded=u32(b,0x128);
        int valid=0; Address entry=null;
        for (long mask : new long[]{0xA8FC57ABL,0x94859D4BL,0x40B5C16EL}) {
            Address a=toAddr(encoded^mask); MemoryBlock block=memory.getBlock(a);
            if (block!=null && block.isExecute()) { valid++; entry=a; }
        }
        if (valid!=1) throw new IllegalArgumentException("Ambiguous XBE entry point");
        addEntryPoint(entry);
        disassemble(entry);
        createFunction(entry,"xbox_entry");
        println("XBE mapped at "+Long.toHexString(base)+", entry "+entry);
    }
}
