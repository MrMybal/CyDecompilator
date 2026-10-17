"""Compile desktop applications with resources, dependencies and compact identifiers.

These are reproducible integration applications, not third-party application claims.
The GUI is constructed on an STA thread but never shown during tests.
"""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cydec import process, service, workspace
from cydec.engines.base import EngineContext
from cydec.project import ProjectStore


@pytest.mark.parametrize('kind', ['WinForms', 'WPF'])
def test_desktop_resource_dependency_decompile_rebuild_and_reinject(tmp_path, monkeypatch, kind):
    if sys.platform != 'win32':
        pytest.skip('Windows desktop integration needs Windows')
    ctx = EngineContext(workdir=tmp_path / 'work', options={'symbols': False})
    sdk = workspace.dotnet_sdk(ctx)
    _, out, _ = process.run([sdk, '--version'], context=ctx)
    version = out.strip().split('.')[0]
    source, dependency = tmp_path / 'source', tmp_path / 'dependency'
    source.mkdir(); dependency.mkdir()
    (dependency / 'Support.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        f'<TargetFramework>net{version}.0</TargetFramework></PropertyGroup></Project>', encoding='utf-8')
    (dependency / 'Helper.cs').write_text('namespace Support; public class a { public static string b()=>"dependency"; }', encoding='utf-8')
    properties = '<UseWindowsForms>true</UseWindowsForms>' if kind == 'WinForms' else '<UseWPF>true</UseWPF>'
    (source / 'Desktop.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        f'<TargetFramework>net{version}.0-windows</TargetFramework><OutputType>Exe</OutputType>{properties}'
        '</PropertyGroup><ItemGroup><ProjectReference Include="../dependency/Support.csproj" />'
        '<EmbeddedResource Include="Message.txt" LogicalName="Message.txt" /></ItemGroup></Project>', encoding='utf-8')
    (source / 'Message.txt').write_text('resource-value', encoding='utf-8')
    if kind == 'WinForms':
        setup = 'using var form=new System.Windows.Forms.Form(); form.Text=value; string title=form.Text;'
    else:
        setup = 'var window=new View(); window.InitializeComponent(); window.Title=value; string title=window.Title;'
        (source / 'View.xaml').write_text('<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
            'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" x:Class="View" Title="Recovered"><Grid>'
            '<TextBlock x:Name="Caption" Text="BAML resource" /></Grid></Window>', encoding='utf-8')
        (source / 'View.xaml.cs').write_text('public partial class View : System.Windows.Window { public View(){} }', encoding='utf-8')
    (source / 'Program.cs').write_text('using System; using System.IO; using System.Reflection; class Program { '
        'static int Compute(int v)=>v+1; [STAThread] static void Main(){'
        'using var stream=Assembly.GetExecutingAssembly().GetManifestResourceStream("Message.txt"); '
        'string value=new StreamReader(stream).ReadToEnd(); ' + setup +
        'Console.WriteLine(title+":"+Support.a.b()+":"+Compute(3)); }}', encoding='utf-8')
    original = tmp_path / 'original'
    rc, out, err = process.run([sdk, 'build', str(source), '-o', str(original)], context=ctx, timeout=180)
    assert rc == 0, out + err
    rc, out, err = process.run([sdk, str(original / 'Desktop.dll')], context=ctx, timeout=30)
    assert rc == 0 and 'resource-value:dependency:4' in out, out + err
    monkeypatch.setattr(service, 'store', ProjectStore(tmp_path / 'projects'))
    project, _ = service.store.open(original / 'Desktop.dll')
    before = hashlib.sha256(project.binary.read_bytes()).hexdigest()
    service.analyze(project.id, 'ilspy', ctx)
    reconstructed = service.workspace_create(project.id, context=ctx)
    root = Path(reconstructed['directory'])
    result = service.workspace_execute(project.id, 'build', ctx)
    assert result['status'] == 'passed', result['output']
    result = service.workspace_execute(project.id, 'run', ctx)
    assert result['status'] == 'passed' and 'resource-value:dependency:4' in result['output'], result['output']
    filename = next(p['path'] for p in service.workspace_info(project.id)['files'] if p['path'].endswith('Program.cs'))
    read = service.workspace_read(project.id, filename)
    text = read['text'].replace('v + 1', 'v + 40')
    assert text != read['text']
    service.workspace_save(project.id, filename, text, read['revision'])
    method = next(m for m in service.managed_methods(project.id, ctx)['methods'] if m['name'] == 'Compute')
    plan = service.managed_patch_prepare(project.id, method['id'], ctx, symbols=True)
    receipt = service.patch_apply(project.id, plan['planId'], context=ctx)
    result = service.patch_run(project.id, receipt['receiptId'], ctx)
    assert result['status'] == 'passed' and 'resource-value:dependency:43' in result['output'], result['output']
    assert hashlib.sha256(project.binary.read_bytes()).hexdigest() == before
