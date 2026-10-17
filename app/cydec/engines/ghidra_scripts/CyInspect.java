// Read-only, bounded function dossier with instruction, type and SSA p-code evidence.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.pcode.*;
import ghidra.program.model.symbol.*;
import java.nio.file.*;
import java.util.*;

public class CyInspect extends GhidraScript {
    private Map<String,Object> map(Object... pairs) {
        Map<String,Object> result=new LinkedHashMap<>();
        for(int i=0;i<pairs.length;i+=2) result.put((String)pairs[i],pairs[i+1]);
        return result;
    }
    private String json(Object value) {
        if(value==null) return "null";
        if(value instanceof Number || value instanceof Boolean) return value.toString();
        if(value instanceof Map) { List<String> parts=new ArrayList<>();
            for(Object obj:((Map<?,?>)value).entrySet()) { Map.Entry<?,?> e=(Map.Entry<?,?>)obj;
                parts.add(json(e.getKey())+":"+json(e.getValue())); } return "{"+String.join(",",parts)+"}"; }
        if(value instanceof Iterable) { List<String> parts=new ArrayList<>();
            for(Object obj:(Iterable<?>)value) parts.add(json(obj)); return "["+String.join(",",parts)+"]"; }
        String s=value.toString(); StringBuilder b=new StringBuilder("\"");
        for(char c:s.toCharArray()) { if(c=='"'||c=='\\') b.append('\\').append(c);
            else if(c<32) b.append(String.format("\\u%04x",(int)c)); else b.append(c); }
        return b.append('"').toString();
    }
    private Map<String,Object> type(DataType dt,int depth) {
        Map<String,Object> result=map("name",dt.getPathName(),"size",dt.getLength(),"kind",dt.getClass().getSimpleName());
        if(depth>=3) { result.put("depthLimited",true); return result; }
        if(dt instanceof Pointer) { DataType target=((Pointer)dt).getDataType();
            if(target!=null) result.put("target",type(target,depth+1)); }
        if(dt instanceof Array) { result.put("count",((Array)dt).getNumElements());
            result.put("element",type(((Array)dt).getDataType(),depth+1)); }
        if(dt instanceof Composite) { List<Object> fields=new ArrayList<>();
            DataTypeComponent[] cs=((Composite)dt).getComponents();
            for(int i=0;i<Math.min(cs.length,128);i++) { DataTypeComponent c=cs[i];
                fields.add(map("name",c.getFieldName(),"offset",c.getOffset(),"size",c.getLength(),
                               "type",type(c.getDataType(),depth+1))); }
            result.put("fields",fields); result.put("fieldsLimited",cs.length>128); }
        return result;
    }
    private List<Object> variables=new ArrayList<>();
    private IdentityHashMap<Varnode,Integer> ids=new IdentityHashMap<>();
    private int variable(Varnode v) {
        if(ids.containsKey(v)) return ids.get(v);
        int id=ids.size(); ids.put(v,id);
        Map<String,Object> row=map("id",id,"storage",v.getAddress().toString(),"size",v.getSize(),
                                  "constant",v.isConstant(),"value",Long.toUnsignedString(v.getOffset()));
        if(v instanceof VarnodeAST) { HighVariable high=((VarnodeAST)v).getHigh();
            if(high!=null) { row.put("name",high.getName()); row.put("type",type(high.getDataType(),0)); } }
        variables.add(row); return id;
    }
    @Override protected void run() throws Exception {
        String[] args=getScriptArgs();
        if(args.length!=2) throw new IllegalArgumentException("output, function address required");
        Address address=currentProgram.getAddressFactory().getAddress(args[1]);
        Function fn=currentProgram.getFunctionManager().getFunctionAt(address);
        if(fn==null) throw new IllegalArgumentException("Function not found");
        Map<String,Object> report=map("address",fn.getEntryPoint().toString(),"name",fn.getName(true),
            "prototype",fn.getPrototypeString(false,false),"callingConvention",fn.getCallingConventionName(),
            "returnType",type(fn.getReturnType(),0));
        List<Object> parameters=new ArrayList<>();
        for(Parameter p:fn.getParameters()) parameters.add(map("name",p.getName(),"ordinal",p.getOrdinal(),
            "storage",p.getVariableStorage().toString(),"type",type(p.getDataType(),0)));
        report.put("parameters",parameters);
        List<Object> instructions=new ArrayList<>(), references=new ArrayList<>();
        InstructionIterator iterator=currentProgram.getListing().getInstructions(fn.getBody(),true);
        int count=0;
        while(iterator.hasNext() && count<2000) {
            monitor.checkCancelled(); Instruction ins=iterator.next(); count++;
            instructions.add(map("address",ins.getAddress().toString(),"text",ins.toString(),"length",ins.getLength()));
            for(Reference ref:ins.getReferencesFrom()) {
                Function target=currentProgram.getFunctionManager().getFunctionAt(ref.getToAddress());
                Data data=currentProgram.getListing().getDataAt(ref.getToAddress());
                String string=data!=null && data.getValue() instanceof String ? (String)data.getValue() : null;
                references.add(map("from",ins.getAddress().toString(),"to",ref.getToAddress().toString(),
                    "kind",ref.getReferenceType().toString(),"call",ref.getReferenceType().isCall(),
                    "targetFunction",target!=null?target.getName(true):null,"string",string!=null?string.substring(0,Math.min(1000,string.length())):null));
            }
        }
        report.put("instructions",instructions); report.put("references",references);
        report.put("instructionsLimited",iterator.hasNext());
        DecompInterface decompiler=new DecompInterface();
        try {
            decompiler.toggleCCode(false); decompiler.toggleSyntaxTree(true); decompiler.openProgram(currentProgram);
            DecompileResults result=decompiler.decompileFunction(fn,90,monitor);
            monitor.checkCancelled();
            HighFunction high=result.getHighFunction();
            List<Object> operations=new ArrayList<>();
            if(high!=null) { Iterator<PcodeOpAST> ops=high.getPcodeOps(); int opCount=0;
                while(ops.hasNext() && opCount<1500) { monitor.checkCancelled(); PcodeOpAST op=ops.next();
                    List<Integer> inputs=new ArrayList<>(); for(int i=0;i<op.getNumInputs();i++) inputs.add(variable(op.getInput(i)));
                    operations.add(map("id",opCount++,"address",op.getSeqnum().getTarget().toString(),
                        "opcode",op.getMnemonic(),"inputs",inputs,"output",op.getOutput()!=null?variable(op.getOutput()):null));
                } report.put("valuesLimited",ops.hasNext());
            } else report.put("decompilerError",result.getErrorMessage());
            report.put("operations",operations); report.put("values",variables);
        } finally { decompiler.dispose(); }
        monitor.checkCancelled();
        Files.writeString(Path.of(args[0]),json(report));
    }
}
