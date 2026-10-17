// Patch metadata without loading or executing the application being analyzed.
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using dnlib.DotNet;
using dnlib.DotNet.Emit;
using dnlib.DotNet.Writer;
using dnlib.DotNet.Pdb;

sealed class Request {
    public string Operation { get; set; }
    public string Original { get; set; }
    public string Donor { get; set; }
    public string Output { get; set; }
    public string Type { get; set; }
    public uint Token { get; set; }
    public bool RemoveStrongName { get; set; }
    public bool AllowNewMembers { get; set; }
    public bool Symbols { get; set; }
}

static class Program {
    static string Attr(string name) => "System.Runtime.CompilerServices." + name;
    static bool GeneratedMethod(MethodDef m) => m.CustomAttributes.Any(a =>
        a.TypeFullName == Attr("AsyncStateMachineAttribute") || a.TypeFullName == Attr("IteratorStateMachineAttribute") ||
        a.TypeFullName == Attr("AsyncIteratorStateMachineAttribute"));
    static string Constraints(IList<GenericParam> parameters) => string.Join(";", parameters.Select(p =>
        p.Number + ":" + p.Flags + ":" + string.Join(",", p.GenericParamConstraints.Select(c => c.Constraint.FullName).OrderBy(s => s))));
    static string NormalizeType(string name) => name.Replace('/', '+');
    // Generic parameter display names depend on dnlib's read/import context (T vs
    // !!0). Verify the actual signature structure and parameter number instead.
    static string TypeName(ITypeDefOrRef type) => type is TypeSpec spec ? TypeSignature(spec.TypeSig) : type?.FullName ?? "";
    static string TypeSignature(TypeSig type) => type switch {
        null => "", GenericMVar v => "!!" + v.Number, GenericVar v => "!" + v.Number,
        GenericInstSig g => TypeName(g.GenericType.TypeDefOrRef) + "<" + string.Join(",", g.GenericArguments.Select(TypeSignature)) + ">",
        TypeDefOrRefSig t => t.ElementType + ":" + TypeName(t.TypeDefOrRef),
        ModifierSig m => m.ElementType + ":" + TypeName(m.Modifier) + ":" + TypeSignature(m.Next),
        ArraySig a => "array:" + a.Rank + ":" + string.Join(",", a.Sizes) + ":" + string.Join(",", a.LowerBounds) + ":" + TypeSignature(a.Next),
        FnPtrSig f => "fnptr:" + Signature(f.Signature),
        _ => type.ElementType + ":" + TypeSignature(type.Next)
    };
    static string Signature(CallingConventionSig signature) => signature switch {
        MethodBaseSig m => m.CallingConvention + ":" + m.GenParamCount + ":" + TypeSignature(m.RetType) +
            "(" + string.Join(",", m.Params.Select(TypeSignature)) + ")(" +
            string.Join(",", (m.ParamsAfterSentinel ?? Array.Empty<TypeSig>()).Select(TypeSignature)) + ")",
        FieldSig f => "field:" + TypeSignature(f.Type),
        GenericInstMethodSig g => "generic:" + string.Join(",", g.GenericArguments.Select(TypeSignature)),
        _ => signature?.ToString() ?? ""
    };
    static string MethodName(IMethod method) => method is MethodSpec spec ? MethodName(spec.Method) + Signature(spec.GenericInstMethodSig) :
        TypeName(method.DeclaringType) + "::" + method.Name + ":" + Signature(method.MethodSig);
    static string Fingerprint(MethodDef method) {
        if (!method.HasBody) return "no-body";
        var b = method.Body;
        var indices = b.Instructions.Select((i,n) => (i,n)).ToDictionary(x => x.i, x => x.n);
        string Point(Instruction i) => i == null ? "end" : indices[i].ToString();
        string Operand(object o) => o switch {
            null => "", Instruction i => "branch:" + Point(i), IList<Instruction> a => string.Join(",", a.Select(Point)),
            Local l => "local:" + l.Index, Parameter p => "arg:" + p.Index,
            IMethod m => MethodName(m), IField f => TypeName(f.DeclaringType) + "::" + f.Name + ":" + Signature(f.FieldSig),
            ITypeDefOrRef t => TypeName(t), CallingConventionSig s => Signature(s), string s => JsonSerializer.Serialize(s),
            _ => Convert.ToString(o, System.Globalization.CultureInfo.InvariantCulture)
        };
        var lines = b.Instructions.Select(i => i.OpCode.Code + ":" + Operand(i.Operand));
        var handlers = b.ExceptionHandlers.Select(h => string.Join(";", h.HandlerType, Point(h.TryStart),
            Point(h.TryEnd), Point(h.HandlerStart), Point(h.HandlerEnd), Point(h.FilterStart), TypeName(h.CatchType)));
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join("\n", lines) +
            "\n" + string.Join(";", b.Variables.Select(v => TypeSignature(v.Type))) + "\n" + string.Join("\n", handlers) + ":" + b.InitLocals)));
    }
    static void CheckMethod(MethodDef method) {
        if (!method.HasBody || !method.IsIL || method.IsAbstract || method.IsPinvokeImpl)
            throw new InvalidOperationException("Select a method with an editable IL body.");
        if (OriginalMapper.Generated(method.DeclaringType) || OriginalMapper.Generated(method))
            throw new InvalidOperationException("Select the owning source method instead of a generated helper.");
    }
    internal static CilBody CopyBody(MethodDef source, MethodDef target, OriginalMapper mapper) {
        var importer = mapper.ImporterFor(target.DeclaringType, target);
        source.Body.SimplifyMacros(source.Parameters);
        var body = new CilBody { InitLocals = source.Body.InitLocals, MaxStack = source.Body.MaxStack };
        var locals = new Dictionary<Local, Local>();
        foreach (var v in source.Body.Variables) {
            var local = new Local(importer.Import(v.Type)) { Name = v.Name, Attributes = v.Attributes }; locals[v] = local; body.Variables.Add(local);
        }
        var instructions = new Dictionary<Instruction, Instruction>();
        foreach (var i in source.Body.Instructions) {
            var clone = new Instruction(i.OpCode, null) { SequencePoint = i.SequencePoint?.Clone() }; instructions[i] = clone; body.Instructions.Add(clone);
        }
        object Import(object operand) => operand switch {
            null => null, Instruction i => instructions[i], IList<Instruction> a => a.Select(i => instructions[i]).ToArray(),
            Local l => locals[l], Parameter p => target.Parameters[p.Index],
            MemberRef member => member.IsMethodRef ? (object)importer.Import((IMethod)member) : importer.Import((IField)member),
            ITypeDefOrRef type => importer.Import(type), IMethod method => importer.Import(method), IField field => importer.Import(field),
            MethodSig sig => importer.Import(sig), string or int or long or float or double or byte or sbyte => operand,
            _ => throw new InvalidOperationException("Unsupported IL operand: " + operand.GetType().Name)
        };
        foreach (var i in source.Body.Instructions) instructions[i].Operand = Import(i.Operand);
        Instruction Remap(Instruction i) => i == null ? null : instructions[i];
        foreach (var h in source.Body.ExceptionHandlers)
            body.ExceptionHandlers.Add(new ExceptionHandler(h.HandlerType) { TryStart = Remap(h.TryStart), TryEnd = Remap(h.TryEnd),
                HandlerStart = Remap(h.HandlerStart), HandlerEnd = Remap(h.HandlerEnd), FilterStart = Remap(h.FilterStart),
                CatchType = h.CatchType == null ? null : importer.Import(h.CatchType) });
        if (source.Body.PdbMethod?.Scope != null) {
            PdbScope Scope(PdbScope sourceScope) {
                var scope = new PdbScope { Start = Remap(sourceScope.Start), End = Remap(sourceScope.End) };
                foreach (var variable in sourceScope.Variables)
                    scope.Variables.Add(new PdbLocal(locals[variable.Local], variable.Name, variable.Attributes));
                foreach (var child in sourceScope.Scopes) scope.Scopes.Add(Scope(child));
                return scope;
            }
            body.PdbMethod = new PdbMethod { Scope = Scope(source.Body.PdbMethod.Scope) };
        }
        // Debugger async/iterator stepping records contain method/instruction handles.
        // Remap them instead of carrying tokens from the rebuilt assembly.
        foreach (var info in source.CustomDebugInfos) {
            if (info is PdbAsyncMethodCustomDebugInfo asyncInfo) {
                var copy = new PdbAsyncMethodCustomDebugInfo { KickoffMethod = (MethodDef)mapper.Map(asyncInfo.KickoffMethod),
                    CatchHandlerInstruction = Remap(asyncInfo.CatchHandlerInstruction) };
                foreach (var step in asyncInfo.StepInfos) {
                    if (step.BreakpointMethod != source)
                        throw new InvalidOperationException("Cross-method async stepping metadata is unsupported.");
                    copy.StepInfos.Add(new PdbAsyncStepInfo(Remap(step.YieldInstruction), target, Remap(step.BreakpointInstruction)));
                }
                target.CustomDebugInfos.Add(copy);
            } else if (info is PdbIteratorMethodCustomDebugInfo iteratorInfo)
                target.CustomDebugInfos.Add(new PdbIteratorMethodCustomDebugInfo((MethodDef)mapper.Map(iteratorInfo.KickoffMethod)));
        }
        body.OptimizeMacros(); body.UpdateInstructionOffsets();
        return body;
    }
    static object Execute(Request r) {
        using var original = ModuleDefMD.Load(r.Original);
        if (!original.IsILOnly) throw new InvalidOperationException("Mixed-mode assemblies cannot be patched by this tool.");
        var all = original.GetTypes().SelectMany(t => t.Methods).ToArray();
        if (r.Operation == "list") {
            var selected = all.Where(m => string.IsNullOrEmpty(r.Type) || NormalizeType(m.DeclaringType.FullName) == NormalizeType(r.Type));
            return new { assembly = original.Assembly?.FullName, module = original.Name.String,
                signed = original.IsStrongNameSigned || original.Assembly?.HasPublicKey == true,
                methods = selected.Select(m => new { id = "0x" + m.MDToken.Raw.ToString("x8"), token = m.MDToken.Raw,
                    name = m.Name.String, type = m.DeclaringType.FullName, signature = m.FullName,
                    editable = m.HasBody && m.IsIL && !OriginalMapper.Generated(m.DeclaringType) && !OriginalMapper.Generated(m),
                    generatedKind = OriginalMapper.Generated(m.DeclaringType) || OriginalMapper.Generated(m) ? "helper" :
                        GeneratedMethod(m) ? "state-machine" : "", instructions = m.Body?.Instructions.Count ?? 0 }).ToArray() };
        }
        if (r.Operation != "patch") throw new InvalidOperationException("Unknown operation.");
        if (File.Exists(r.Output)) throw new InvalidOperationException("The output already exists.");
        var target = original.ResolveToken(r.Token) as MethodDef ?? throw new InvalidOperationException("Method token not found.");
        CheckMethod(target);
        using var donor = ModuleDefMD.Load(r.Donor, new ModuleCreationOptions { TryToLoadPdbFromDisk = r.Symbols });
        if (r.Symbols && donor.PdbState == null) throw new InvalidOperationException("Build the donor with portable debug symbols before preparing a debug copy.");
        if (donor.Assembly?.Name != original.Assembly?.Name)
            throw new InvalidOperationException("The rebuilt project's assembly name differs from the original.");
        var candidates = donor.GetTypes().SelectMany(t => t.Methods).Where(m => m.FullName == target.FullName).ToArray();
        if (candidates.Length != 1) throw new InvalidOperationException("No unique replacement with the original type, return type and parameter signature was found.");
        var replacement = candidates[0];
        CheckMethod(replacement);
        if (target.IsStatic != replacement.IsStatic || target.MethodSig.CallingConvention != replacement.MethodSig.CallingConvention ||
            Constraints(target.GenericParameters) != Constraints(replacement.GenericParameters) ||
            Constraints(target.DeclaringType.GenericParameters) != Constraints(replacement.DeclaringType.GenericParameters))
            throw new InvalidOperationException("The replacement changes the calling convention or generic signature.");
        var before = all.ToDictionary(m => m.MDToken.Raw, m => (m.FullName, Body: Fingerprint(m)));
        var oldTypes = original.GetTypes().ToDictionary(t => t.MDToken.Raw, t => t.FullName);
        var oldFields = original.GetTypes().SelectMany(t => t.Fields).ToDictionary(f => f.MDToken.Raw, f => f.FullName);
        bool signed = original.IsStrongNameSigned || original.Assembly?.HasPublicKey == true;
        if (signed && !r.RemoveStrongName)
            throw new InvalidOperationException("The assembly has a strong-name signature. Explicitly allow removing it or rebuild and sign with the original key.");
        var mapper = new OriginalMapper(original, donor, r.AllowNewMembers);
        var body = CopyBody(replacement, target, mapper);
        uint oldSize = (uint)target.Body.Instructions.Sum(i => i.GetSize());
        target.Body = body;
        // Reflection/debugger metadata must name the isolated state machine, too.
        var stateAttributes = new[] { Attr("AsyncStateMachineAttribute"), Attr("IteratorStateMachineAttribute"), Attr("AsyncIteratorStateMachineAttribute") };
        foreach (var attribute in target.CustomAttributes.Where(a => stateAttributes.Contains(a.TypeFullName)).ToArray())
            target.CustomAttributes.Remove(attribute);
        foreach (var attribute in replacement.CustomAttributes.Where(a => stateAttributes.Contains(a.TypeFullName)))
            target.CustomAttributes.Add(mapper.CopyAttribute(attribute, mapper.ImporterFor(target.DeclaringType, target)));
        mapper.Complete();
        string expected = Fingerprint(target);
        var addedMethods = mapper.AddedMethods.ToDictionary(m => m.FullName, Fingerprint);
        if (signed) {
            original.IsStrongNameSigned = false;
            original.Assembly.PublicKey = new PublicKey();
            original.Assembly.Attributes &= ~AssemblyAttributes.PublicKey;
        }
        var options = new ModuleWriterOptions(original);
        options.MetadataOptions.Flags |= MetadataFlags.PreserveAll;
        if (r.Symbols) {
            original.CreatePdbState(PdbFileKind.PortablePDB);
            options.WritePdb = true;
            options.PdbFileName = Path.ChangeExtension(r.Output, ".pdb");
            options.PdbFileNameInDebugDirectory = Path.ChangeExtension(Path.GetFileName(r.Original), ".pdb");
            options.PdbOptions = PdbWriterOptions.None;
        }
        original.Write(r.Output, options);
        using var written = ModuleDefMD.Load(r.Output);
        foreach (var method in written.GetTypes().SelectMany(t => t.Methods)) {
            if (!before.TryGetValue(method.MDToken.Raw, out var saved)) {
                if (!addedMethods.TryGetValue(method.FullName, out var added) || Fingerprint(method) != added)
                    throw new InvalidOperationException("Unexpected or invalid generated method: " + method.FullName);
                continue;
            }
            if (method.FullName != saved.FullName || Fingerprint(method) != (method.MDToken.Raw == r.Token ? expected : saved.Body))
                throw new InvalidOperationException("Method verification failed: " + method.FullName);
        }
        if (written.GetTypes().Sum(t => t.Methods.Count) != all.Length + addedMethods.Count)
            throw new InvalidOperationException("The method count changed unexpectedly.");
        foreach (var row in oldTypes)
            if ((written.ResolveToken(row.Key) as TypeDef)?.FullName != row.Value)
                throw new InvalidOperationException("An original type token changed.");
        foreach (var row in oldFields)
            if ((written.ResolveToken(row.Key) as FieldDef)?.FullName != row.Value)
                throw new InvalidOperationException("An original field token changed.");
        return new { method = target.FullName, token = r.Token, oldSize, newSize = (uint)body.Instructions.Sum(i => i.GetSize()),
            unchangedMethods = all.Length - 1, strongNameRemoved = signed,
            generatedTypes = mapper.GeneratedTypes.Select(t => t.FullName).ToArray(),
            generatedMethods = mapper.GeneratedMethods.Select(m => m.FullName).ToArray(),
            addedTypes = mapper.AddedTypes.Select(t => t.FullName).ToArray(),
            addedMethods = mapper.AddedMethods.Select(m => m.FullName).ToArray(),
            addedFields = mapper.AddedFields.Select(f => f.FullName).ToArray(), symbols = r.Symbols,
            il = string.Join("\n", body.Instructions.Select(i => i.ToString())) };
    }
    static int Main(string[] args) {
        try {
            var request = JsonSerializer.Deserialize<Request>(Console.In.ReadToEnd(), new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            Console.WriteLine(JsonSerializer.Serialize(Execute(request)));
            return 0;
        } catch (Exception e) {
            Console.Error.WriteLine(e.Message);
            return 1;
        }
    }
}
