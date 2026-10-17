using dnlib.DotNet;

// Generated dependencies are copied under fresh names. Existing closure/state-machine
// definitions are never reused: a <>c cache may serve several unrelated source methods.
sealed class OriginalMapper : ImportMapper {
    readonly ModuleDef original, donor;
    readonly Dictionary<string, TypeDef> types, donorTypes;
    readonly Dictionary<string, MethodDef> methods;
    readonly Dictionary<string, FieldDef> fields;
    readonly Dictionary<TypeDef, TypeDef> generatedTypes = new();
    readonly Dictionary<MethodDef, MethodDef> generatedMethods = new();
    readonly Dictionary<FieldDef, FieldDef> generatedFields = new();
    readonly Queue<Action> pending = new();
    readonly string suffix = "__cydec_" + Guid.NewGuid().ToString("N");
    readonly bool allowNewMembers;
    public IEnumerable<TypeDef> AddedTypes => generatedTypes.Values;
    public IEnumerable<MethodDef> AddedMethods => generatedMethods.Values;
    public IEnumerable<FieldDef> AddedFields => generatedFields.Values;
    public IEnumerable<TypeDef> GeneratedTypes => generatedTypes.Where(p => Generated(p.Key)).Select(p => p.Value);
    public IEnumerable<MethodDef> GeneratedMethods => generatedMethods.Where(p => Generated(p.Key) || Generated(p.Key.DeclaringType)).Select(p => p.Value);
    public static bool Generated(IHasCustomAttribute item) => item.CustomAttributes.IsDefined("System.Runtime.CompilerServices.CompilerGeneratedAttribute") ||
        item is TypeDef type && type.DeclaringType != null && Generated(type.DeclaringType);
    public OriginalMapper(ModuleDef original, ModuleDef donor, bool allowNewMembers = false) {
        this.allowNewMembers = allowNewMembers;
        this.original = original; this.donor = donor;
        types = original.GetTypes().ToDictionary(t => t.FullName);
        donorTypes = donor.GetTypes().ToDictionary(t => t.FullName);
        methods = original.GetTypes().SelectMany(t => t.Methods).ToDictionary(m => m.FullName);
        fields = original.GetTypes().SelectMany(t => t.Fields).ToDictionary(f => f.FullName);
    }
    public Importer ImporterFor(TypeDef type, MethodDef method = null) => new Importer(original,
        ImporterOptions.TryToUseDefs | ImporterOptions.TryToUseExistingAssemblyRefs, new GenericParamContext(type, method), this);
    bool Own(ITypeDefOrRef type) => type != null &&
        (type.Module == donor && type is TypeDef || type.DefinitionAssembly?.Name == donor.Assembly?.Name);
    TypeDef SourceType(ITypeDefOrRef type) {
        if (type is TypeSpec spec && spec.TypeSig is GenericInstSig inst)
            type = inst.GenericType.TypeDefOrRef;
        return type != null && donorTypes.TryGetValue(type.FullName, out var definition) ? definition : null;
    }
    string UniqueTypeName(string name) {
        int arity = name.LastIndexOf('`');
        return arity < 0 ? name + suffix : name[..arity] + suffix + name[arity..];
    }
    void Bound() {
        if (generatedTypes.Count > 64 || generatedMethods.Count > 1000 || generatedFields.Count > 2000)
            throw new InvalidOperationException("Generated dependency graph is too large; rebuild the application.");
    }
    static void GenericShells(IList<GenericParam> source, IList<GenericParam> target) {
        foreach (var parameter in source)
            target.Add(new GenericParamUser(parameter.Number, parameter.Flags, parameter.Name));
    }
    void GenericDetails(IList<GenericParam> source, IList<GenericParam> target, Importer importer) {
        for (int i = 0; i < source.Count; i++) {
            foreach (var constraint in source[i].GenericParamConstraints)
                target[i].GenericParamConstraints.Add(new GenericParamConstraintUser(importer.Import(constraint.Constraint)));
            foreach (var attribute in source[i].CustomAttributes)
                target[i].CustomAttributes.Add(CopyAttribute(attribute, importer));
        }
    }
    public override ITypeDefOrRef Map(ITypeDefOrRef source) {
        if (!Own(source) || source is TypeSpec) return null;
        var definition = SourceType(source);
        if (definition != null && Generated(definition)) return CloneType(definition);
        if (types.TryGetValue(source.FullName, out var type)) return type;
        if (allowNewMembers && definition != null) return CloneType(definition);
        throw new InvalidOperationException("The replacement introduces a new type: " + source.FullName);
    }
    TypeDef CloneType(TypeDef source) {
        if (generatedTypes.TryGetValue(source, out var old)) return old;
        if ((Generated(source) && source.IsInterface) || source.HasDeclSecurities)
            throw new InvalidOperationException("Unsupported generated type: " + source.FullName);
        var clone = new TypeDefUser(source.Namespace, Generated(source) ? UniqueTypeName(source.Name) : source.Name.String) { Attributes = source.Attributes };
        generatedTypes[source] = clone; Bound();
        GenericShells(source.GenericParameters, clone.GenericParameters);
        if (source.DeclaringType == null) original.Types.Add(clone);
        else ((TypeDef)Map(source.DeclaringType)).NestedTypes.Add(clone);
        pending.Enqueue(() => {
            var importer = ImporterFor(clone);
            clone.BaseType = source.BaseType == null ? null : importer.Import(source.BaseType);
            if (source.ClassLayout != null)
                clone.ClassLayout = new ClassLayoutUser(source.ClassLayout.PackingSize, source.ClassLayout.ClassSize);
            foreach (var implementation in source.Interfaces)
                clone.Interfaces.Add(new InterfaceImplUser(importer.Import(implementation.Interface)));
            GenericDetails(source.GenericParameters, clone.GenericParameters, importer);
            foreach (var attribute in source.CustomAttributes) clone.CustomAttributes.Add(CopyAttribute(attribute, importer));
            // <>c is a shared singleton cache: copy only fields and lambda bodies reached
            // by the replacement, plus its constructor/static initialisation. Other
            // generated layouts keep all fields, virtual/interface methods and properties.
            bool singleton = source.Name == "<>c" || source.Name.String.StartsWith("<>c`") ||
                source.Name == "<>O" || source.Name.String.StartsWith("<>O`");
            if (!singleton)
                foreach (var field in source.Fields) CloneField(field);
            foreach (var method in source.Methods.Where(m => !Generated(source) || m.IsConstructor || m.IsStaticConstructor || m.IsVirtual))
                CloneMethod(method);
            if (!singleton) {
                foreach (var property in source.Properties) {
                    var p = new PropertyDefUser(property.Name, importer.Import(property.PropertySig), property.Attributes);
                    foreach (var getter in property.GetMethods) p.GetMethods.Add(CloneMethod(getter));
                    foreach (var setter in property.SetMethods) p.SetMethods.Add(CloneMethod(setter));
                    foreach (var other in property.OtherMethods) p.OtherMethods.Add(CloneMethod(other));
                    clone.Properties.Add(p);
                }
                foreach (var sourceEvent in source.Events) {
                    var e = new EventDefUser(sourceEvent.Name, importer.Import(sourceEvent.EventType), sourceEvent.Attributes);
                    if (sourceEvent.AddMethod != null) e.AddMethod = CloneMethod(sourceEvent.AddMethod);
                    if (sourceEvent.RemoveMethod != null) e.RemoveMethod = CloneMethod(sourceEvent.RemoveMethod);
                    if (sourceEvent.InvokeMethod != null) e.InvokeMethod = CloneMethod(sourceEvent.InvokeMethod);
                    foreach (var other in sourceEvent.OtherMethods) e.OtherMethods.Add(CloneMethod(other));
                    foreach (var attribute in sourceEvent.CustomAttributes) e.CustomAttributes.Add(CopyAttribute(attribute, importer));
                    clone.Events.Add(e);
                }
            }
        });
        return clone;
    }
    public override IMethod Map(MethodDef source) {
        if (source.Module != donor) return null;
        if (Generated(source.DeclaringType) || Generated(source)) return CloneMethod(source);
        if (methods.TryGetValue(source.FullName, out var method) && method.IsStatic == source.IsStatic) return method;
        if (allowNewMembers && (!types.ContainsKey(source.DeclaringType.FullName) ||
            (!source.IsConstructor && !source.IsStaticConstructor && !source.IsVirtual))) return CloneMethod(source);
        throw new InvalidOperationException("The replacement introduces or changes a method: " + source.FullName);
    }
    MethodDef CloneMethod(MethodDef source) {
        if (generatedMethods.TryGetValue(source, out var old)) return old;
        bool newOwner = !types.ContainsKey(source.DeclaringType.FullName) && !Generated(source.DeclaringType);
        if ((!source.IsIL || !source.HasBody) && !(newOwner && source.IsAbstract) || source.IsPinvokeImpl || source.HasDeclSecurities)
            throw new InvalidOperationException("Unsupported generated method: " + source.FullName);
        if (source.Body?.Instructions.Count > 100000)
            throw new InvalidOperationException("Generated method is too large; rebuild the application.");
        var owner = (TypeDef)Map(source.DeclaringType);
        var clone = new MethodDefUser(Generated(source) && !Generated(source.DeclaringType) ? source.Name + suffix : source.Name,
                                     null, source.ImplAttributes, source.Attributes);
        generatedMethods[source] = clone; Bound(); owner.Methods.Add(clone);
        GenericShells(source.GenericParameters, clone.GenericParameters);
        var importer = ImporterFor(owner, clone);
        clone.MethodSig = importer.Import(source.MethodSig);
        clone.Parameters.UpdateParameterTypes();
        pending.Enqueue(() => {
            GenericDetails(source.GenericParameters, clone.GenericParameters, importer);
            foreach (var parameter in source.ParamDefs) {
                if (parameter.HasMarshalType) throw new InvalidOperationException("Generated marshalling parameters are unsupported.");
                var p = new ParamDefUser(parameter.Name, parameter.Sequence, parameter.Attributes);
                if (parameter.Constant != null) p.Constant = new ConstantUser(parameter.Constant.Value, parameter.Constant.Type);
                foreach (var attribute in parameter.CustomAttributes) p.CustomAttributes.Add(CopyAttribute(attribute, importer));
                clone.ParamDefs.Add(p);
            }
            foreach (var attribute in source.CustomAttributes) clone.CustomAttributes.Add(CopyAttribute(attribute, importer));
            foreach (var methodOverride in source.Overrides)
                clone.Overrides.Add(new MethodOverride((IMethodDefOrRef)importer.Import(methodOverride.MethodBody),
                                                       (IMethodDefOrRef)importer.Import(methodOverride.MethodDeclaration)));
            if (source.HasBody) clone.Body = Program.CopyBody(source, clone, this);
        });
        return clone;
    }
    public override IField Map(FieldDef source) {
        if (source.Module != donor) return null;
        if (Generated(source.DeclaringType)) return CloneField(source);
        if (fields.TryGetValue(source.FullName, out var field) && field.IsStatic == source.IsStatic) return field;
        if (allowNewMembers) {
            if (types.ContainsKey(source.DeclaringType.FullName)) {
                if (!source.IsStatic || source.DeclaringType.HasClassLayout)
                    throw new InvalidOperationException("New instance/layout fields on an existing type require a complete rebuild.");
                if (source.DeclaringType.Methods.Where(m => m.IsStaticConstructor && m.HasBody).SelectMany(m => m.Body.Instructions)
                    .Any(i => i.OpCode.Code == dnlib.DotNet.Emit.Code.Stsfld && i.Operand is IField f && f.FullName == source.FullName))
                    throw new InvalidOperationException("Initialising a new static field would change the existing type initializer; rebuild the application.");
            }
            return CloneField(source);
        }
        throw new InvalidOperationException("The replacement introduces or changes a field: " + source.FullName);
    }
    FieldDef CloneField(FieldDef source) {
        if (generatedFields.TryGetValue(source, out var old)) return old;
        if (source.HasFieldRVA || source.HasMarshalType)
            throw new InvalidOperationException("Generated RVA/marshalling fields require a complete rebuild.");
        var owner = (TypeDef)Map(source.DeclaringType);
        var clone = new FieldDefUser(source.Name, null, source.Attributes);
        generatedFields[source] = clone; Bound(); owner.Fields.Add(clone);
        var importer = ImporterFor(owner);
        clone.FieldSig = importer.Import(source.FieldSig);
        clone.FieldOffset = source.FieldOffset;
        if (source.Constant != null) clone.Constant = new ConstantUser(source.Constant.Value, source.Constant.Type);
        pending.Enqueue(() => {
            foreach (var attribute in source.CustomAttributes) clone.CustomAttributes.Add(CopyAttribute(attribute, importer));
        });
        return clone;
    }
    public override MemberRef Map(MemberRef source) {
        if (!Own(source.DeclaringType)) return null;
        var type = SourceType(source.DeclaringType);
        var importer = ImporterFor(null);
        UTF8String name;
        if (source.IsMethodRef) {
            var method = type?.Methods.SingleOrDefault(m => m.Name == source.Name && m.MethodSig.ToString() == source.MethodSig.ToString());
            if (method == null) throw new InvalidOperationException("The replacement references a missing member: " + source.FullName);
            name = Map(method).Name;
        } else {
            var field = type?.Fields.SingleOrDefault(f => f.Name == source.Name && f.FieldSig.ToString() == source.FieldSig.ToString());
            if (field == null) throw new InvalidOperationException("The replacement references a missing member: " + source.FullName);
            name = Map(field).Name;
        }
        var parent = (IMemberRefParent)importer.Import(source.DeclaringType);
        return source.IsMethodRef ? new MemberRefUser(original, name, importer.Import(source.MethodSig), parent)
                                  : new MemberRefUser(original, name, importer.Import(source.FieldSig), parent);
    }
    public CustomAttribute CopyAttribute(CustomAttribute source, Importer importer) {
        if (source.IsRawBlob) throw new InvalidOperationException("A generated attribute cannot be decoded safely.");
        CAArgument Argument(CAArgument value) {
            object data = value.Value switch {
                TypeSig type => importer.Import(type), ITypeDefOrRef type => importer.Import(type),
                CAArgument argument => Argument(argument), IList<CAArgument> array => array.Select(Argument).ToArray(),
                _ => value.Value
            };
            return new CAArgument(importer.Import(value.Type), data);
        }
        return new CustomAttribute((ICustomAttributeType)importer.Import(source.Constructor), source.ConstructorArguments.Select(Argument),
            source.NamedArguments.Select(a => new CANamedArgument(a.IsField, importer.Import(a.Type), a.Name, Argument(a.Argument))));
    }
    public void Complete() {
        while (pending.Count != 0) pending.Dequeue()();
    }
}
