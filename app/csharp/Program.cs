// Use the SDK's Roslyn services as metadata readers; never evaluate user MSBuild targets.
using System.Reflection;
using System.Text;
using System.Text.Json;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.Completion;
using Microsoft.CodeAnalysis.FindSymbols;
using Microsoft.CodeAnalysis.Host.Mef;
using Microsoft.CodeAnalysis.Text;
using Microsoft.CodeAnalysis.Rename;
using Microsoft.CodeAnalysis.Formatting;

sealed class Source { public string Path { get; set; } public string Text { get; set; } }
sealed class ProjectInput {
    public string Path { get; set; }
    public string Name { get; set; }
    public string[] References { get; set; } = [];
    public string[] Projects { get; set; } = [];
    public string[] Defines { get; set; } = [];
    public string[] Usings { get; set; } = [];
    public bool Executable { get; set; }
    public string LanguageVersion { get; set; }
    public bool Nullable { get; set; }
    public Source[] Sources { get; set; } = [];
}
sealed class Request {
    public string Action { get; set; }
    public string File { get; set; }
    public string Project { get; set; }
    public int Line { get; set; } = 1;
    public int Column { get; set; } = 1;
    public int Limit { get; set; } = 60;
    public string NewName { get; set; }
    public ProjectInput[] Projects { get; set; }
}

static class Program {
    static object Point(SourceText text, int position) {
        position = Math.Clamp(position, 0, text.Length);
        var line = text.Lines.GetLineFromPosition(position);
        return new { line = line.LineNumber + 1, column = text.ToString(TextSpan.FromBounds(line.Start, position)).EnumerateRunes().Count() + 1 };
    }
    static int Position(SourceText text, int line, int column) {
        if (line < 1 || line > text.Lines.Count || column < 1) throw new InvalidOperationException("Invalid editor position.");
        var value = text.Lines[line - 1];
        var runes = value.ToString().EnumerateRunes().ToArray();
        if (column - 1 > runes.Length) throw new InvalidOperationException("Invalid editor column.");
        return value.Start + runes.Take(column - 1).Sum(r => r.Utf16SequenceLength);
    }
    static object Location(Location location) {
        if (!location.IsInSource) return null;
        var span = location.GetLineSpan();
        var point = Point(location.SourceTree.GetText(), location.SourceSpan.Start);
        return new { path = span.Path, point };
    }
    static async Task<object> Execute(Request r) {
        var assemblies = new[] { "Microsoft.CodeAnalysis.Workspaces", "Microsoft.CodeAnalysis.CSharp.Workspaces",
                                  "Microsoft.CodeAnalysis.Features", "Microsoft.CodeAnalysis.CSharp.Features" }.Select(Assembly.Load);
        using var workspace = new AdhocWorkspace(MefHostServices.Create(assemblies));
        var ids = r.Projects.ToDictionary(p => p.Path, p => ProjectId.CreateNewId(p.Name));
        var solution = workspace.CurrentSolution;
        foreach (var project in r.Projects) {
            var references = project.References.Select(p => MetadataReference.CreateFromFile(p)).ToArray();
            LanguageVersionFacts.TryParse(project.LanguageVersion ?? "default", out var version);
            var parse = new CSharpParseOptions(version, preprocessorSymbols: project.Defines);
            var options = new CSharpCompilationOptions(project.Executable ? OutputKind.ConsoleApplication : OutputKind.DynamicallyLinkedLibrary,
                allowUnsafe: true, usings: project.Usings, nullableContextOptions: project.Nullable ? NullableContextOptions.Enable : NullableContextOptions.Disable);
            solution = solution.AddProject(ProjectInfo.Create(ids[project.Path], VersionStamp.Create(), project.Name, project.Name,
                LanguageNames.CSharp, filePath: project.Path, parseOptions: parse, compilationOptions: options, metadataReferences: references));
            foreach (var source in project.Sources)
                solution = solution.AddDocument(DocumentId.CreateNewId(ids[project.Path]), System.IO.Path.GetFileName(source.Path),
                    SourceText.From(source.Text, Encoding.UTF8), filePath: source.Path);
        }
        foreach (var project in r.Projects)
            foreach (var reference in project.Projects)
                solution = solution.AddProjectReference(ids[project.Path], new ProjectReference(ids[reference]));
        if (!workspace.TryApplyChanges(solution)) throw new InvalidOperationException("Could not create the C# project model.");
        solution = workspace.CurrentSolution;
        var current = solution.GetProject(ids[r.Project]);
        var document = current.Documents.SingleOrDefault(d => d.FilePath == r.File) ?? throw new InvalidOperationException("Source file is not in the selected C# project.");
        var text = await document.GetTextAsync();
        int position = Position(text, r.Line, r.Column);
        if (r.Action is "rename" or "format") {
            Solution updated;
            string symbolName = "";
            if (r.Action == "rename") {
                if (!SyntaxFacts.IsValidIdentifier(r.NewName)) throw new InvalidOperationException("Use a valid C# identifier.");
                var symbol = await SymbolFinder.FindSymbolAtPositionAsync(document, position);
                if (symbol == null || !symbol.Locations.Any(l => l.IsInSource)) throw new InvalidOperationException("Select a source symbol to rename.");
                symbolName = symbol.ToDisplayString();
                updated = await Renamer.RenameSymbolAsync(solution, symbol, new SymbolRenameOptions(), r.NewName);
            } else {
                var formatted = await Formatter.FormatAsync(document);
                updated = formatted.Project.Solution;
            }
            var edits = new List<object>();
            foreach (var projectChange in updated.GetChanges(solution).GetProjectChanges())
                foreach (var id in projectChange.GetChangedDocuments()) {
                    var oldDoc = solution.GetDocument(id); var newDoc = updated.GetDocument(id);
                    var oldText = await oldDoc.GetTextAsync(); var newText = await newDoc.GetTextAsync();
                    edits.Add(new { path = oldDoc.FilePath, before = oldText.ToString(), text = newText.ToString() });
                }
            // A rename is rejected if it introduces compiler errors in any affected project.
            if (r.Action == "rename") {
                foreach (var change in updated.GetChanges(solution).GetProjectChanges()) {
                    var oldCompilation = await solution.GetProject(change.ProjectId).GetCompilationAsync();
                    var oldErrors = oldCompilation.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error)
                        .Select(d => d.Id + ":" + d.GetMessage()).ToHashSet();
                    var newCompilation = await updated.GetProject(change.ProjectId).GetCompilationAsync();
                    var introduced = newCompilation.GetDiagnostics().FirstOrDefault(d => d.Severity == DiagnosticSeverity.Error && !oldErrors.Contains(d.Id + ":" + d.GetMessage()));
                    if (introduced != null) throw new InvalidOperationException("Rename introduces a conflict: " + introduced.GetMessage());
                }
            }
            return new { symbol = symbolName, edits };
        }
        if (r.Action == "references") {
            var symbol = await SymbolFinder.FindSymbolAtPositionAsync(document, position);
            if (symbol == null) return new { symbol = "", references = Array.Empty<object>() };
            var references = await SymbolFinder.FindReferencesAsync(symbol, solution);
            return new { symbol = symbol.ToDisplayString(), references = references.SelectMany(s => s.Locations)
                .Select(l => Location(l.Location)).Take(r.Limit).ToArray() };
        }
        if (r.Action == "complete") {
            var service = CompletionService.GetService(document) ?? throw new InvalidOperationException("C# completion services unavailable in this SDK.");
            var list = await service.GetCompletionsAsync(document, position);
            if (list == null) return new { items = Array.Empty<object>(), truncated = false };
            string prefix = text.ToString(TextSpan.FromBounds(list.Span.Start, position));
            var candidates = list.ItemsList.Where(i => i.FilterText.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)).ToArray();
            var items = new List<object>();
            foreach (var item in candidates.Take(r.Limit)) {
                var change = await service.GetChangeAsync(document, item);
                var description = await service.GetDescriptionAsync(document, item);
                var edit = change.TextChange;
                var updated = text.WithChanges(edit);
                items.Add(new { label = item.DisplayTextPrefix + item.DisplayText + item.DisplayTextSuffix,
                    detail = string.Concat(description.TaggedParts.Select(p => p.Text)), tags = item.Tags,
                    edit = new { start = Point(text, edit.Span.Start), end = Point(text, edit.Span.End), text = edit.NewText,
                        cursor = Point(updated, change.NewPosition ?? edit.Span.Start + (edit.NewText?.Length ?? 0)) } });
            }
            return new { items, truncated = candidates.Length > r.Limit };
        }
        if (r.Action == "definition") {
            var symbol = await SymbolFinder.FindSymbolAtPositionAsync(document, position);
            if (symbol == null) return new { symbol = "", definitions = Array.Empty<object>() };
            symbol = await SymbolFinder.FindSourceDefinitionAsync(symbol, solution) ?? symbol;
            return new { symbol = symbol.ToDisplayString(SymbolDisplayFormat.MinimallyQualifiedFormat),
                definitions = symbol.Locations.Where(l => l.IsInSource).Select(Location).ToArray() };
        }
        var compilation = await current.GetCompilationAsync();
        if (r.Action == "diagnostics") {
            var issues = compilation.GetDiagnostics().Where(d => d.Location.IsInSource && d.Severity is DiagnosticSeverity.Error or DiagnosticSeverity.Warning).ToArray();
            return new { diagnostics = issues.Take(r.Limit).Select(d => new { code = d.Id, severity = d.Severity.ToString().ToLowerInvariant(),
                message = d.GetMessage(System.Globalization.CultureInfo.InvariantCulture), location = Location(d.Location) }).ToArray(), truncated = issues.Length > r.Limit };
        }
        if (r.Action == "symbols") {
            var symbols = new List<object>();
            foreach (var source in current.Documents) {
                var root = await source.GetSyntaxRootAsync();
                var model = await source.GetSemanticModelAsync();
                foreach (var node in root.DescendantNodes()) {
                    if (node is not Microsoft.CodeAnalysis.CSharp.Syntax.BaseTypeDeclarationSyntax and not Microsoft.CodeAnalysis.CSharp.Syntax.BaseMethodDeclarationSyntax
                        and not Microsoft.CodeAnalysis.CSharp.Syntax.PropertyDeclarationSyntax and not Microsoft.CodeAnalysis.CSharp.Syntax.VariableDeclaratorSyntax) continue;
                    var symbol = model.GetDeclaredSymbol(node);
                    if (symbol == null || symbol.Kind is not (SymbolKind.NamedType or SymbolKind.Method or SymbolKind.Field or SymbolKind.Property or SymbolKind.Event)) continue;
                    symbols.Add(new { name = symbol.ToDisplayString(SymbolDisplayFormat.MinimallyQualifiedFormat), kind = symbol.Kind.ToString(),
                        location = Location(symbol.Locations.First(l => l.IsInSource)) });
                    if (symbols.Count > r.Limit) break;
                }
                if (symbols.Count > r.Limit) break;
            }
            return new { symbols = symbols.Take(r.Limit), truncated = symbols.Count > r.Limit };
        }
        throw new InvalidOperationException("Unknown C# editor action.");
    }
    static async Task<int> Main() {
        try {
            var request = JsonSerializer.Deserialize<Request>(Console.In.ReadToEnd(), new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            Console.WriteLine(JsonSerializer.Serialize(await Execute(request)));
            return 0;
        } catch (Exception error) {
            Console.Error.WriteLine(error.Message);
            return 1;
        }
    }
}
