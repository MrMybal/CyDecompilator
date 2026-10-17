// Standalone product recorder; uses Windows UI Automation, scoped to owned PIDs.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Automation;

class DesktopCapture {
    static JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=16*1024*1024 };
    static string PidsFile, Folder, Output;
    static List<object> Steps=new List<object>(), States=new List<object>(), Unknowns=new List<object>();
    static Dictionary<string,object> Result;
    static long ImageBytes;
    static Dictionary<string,object> Obj(params object[] fields) {
        var d=new Dictionary<string,object>(); for(int i=0;i<fields.Length;i+=2)d[(string)fields[i]]=fields[i+1];return d;
    }
    static string Str(Dictionary<string,object> d,string key,string fallback="") {return d.ContainsKey(key)?Convert.ToString(d[key]):fallback;}
    static int Num(Dictionary<string,object> d,string key,int fallback) {return d.ContainsKey(key)?Convert.ToInt32(d[key]):fallback;}
    static string Hash(byte[] data) {using(var h=SHA256.Create())return BitConverter.ToString(h.ComputeHash(data)).Replace("-","").ToLowerInvariant();}
    static void Save() {
        File.WriteAllText(Output+".tmp",Json.Serialize(Result),new UTF8Encoding(false));
        if(File.Exists(Output))File.Delete(Output);File.Move(Output+".tmp",Output);
    }
    static HashSet<int> Owned() {
        var result=new HashSet<int>();
        var rows=(object[])Json.DeserializeObject(File.ReadAllText(PidsFile));
        foreach(Dictionary<string,object> row in rows) {
            try {int pid=Num(row,"pid",0);using(var process=Process.GetProcessById(pid)) {
                double start=(process.StartTime.ToUniversalTime()-new DateTime(1970,1,1)).TotalSeconds;
                if(Math.Abs(start-Convert.ToDouble(row["created"]))<0.05)result.Add(pid);
            }}catch(ArgumentException){}catch(InvalidOperationException){}
        }return result;
    }
    static List<AutomationElement> Windows() {
        var owned=Owned();var result=new List<AutomationElement>();
        foreach(AutomationElement e in AutomationElement.RootElement.FindAll(TreeScope.Children,Condition.TrueCondition)) {
            try {if(owned.Contains(e.Current.ProcessId))result.Add(e);}catch(ElementNotAvailableException){}
        }return result;
    }
    static void Walk(AutomationElement e,List<AutomationElement> result,int depth) {
        if(result.Count>=1000 || depth>16) {if(!Unknowns.Contains("uia-element-limit"))Unknowns.Add("uia-element-limit");return;}
        result.Add(e);
        var walker=TreeWalker.ControlViewWalker;
        for(var child=walker.GetFirstChild(e);child!=null;child=walker.GetNextSibling(child)) {
            Walk(child,result,depth+1);if(result.Count>=1000)break;
        }
    }
    static List<AutomationElement> Elements() {
        var result=new List<AutomationElement>();foreach(var w in Windows())Walk(w,result,0);return result;
    }
    static AutomationElement Find(Dictionary<string,object> selector,int timeout) {
        var timer=Stopwatch.StartNew();
        while(timer.ElapsedMilliseconds<=timeout) {
            var matches=new List<AutomationElement>();
            var owned=Owned();
            foreach(var e in Elements()) {
                try {
                    var c=e.Current;
                    if(selector.ContainsKey("automationId") && c.AutomationId!=Str(selector,"automationId"))continue;
                    if(selector.ContainsKey("name") && c.Name!=Str(selector,"name"))continue;
                    if(selector.ContainsKey("controlType") && c.ControlType.ProgrammaticName!="ControlType."+Str(selector,"controlType"))continue;
                    if(!owned.Contains(c.ProcessId))continue;
                    matches.Add(e);
                }catch(ElementNotAvailableException){}
            }
            if(matches.Count>1)throw new Exception("Selector is ambiguous");
            if(matches.Count==1)return matches[0];Thread.Sleep(100);
        }throw new Exception("Control not found before the deadline");
    }
    [DllImport("user32.dll")] static extern bool PrintWindow(IntPtr hwnd,IntPtr hdc,uint flags);
    static object Screen(AutomationElement window,int index,int ordinal) {
        var c=window.Current;var rectangle=c.BoundingRectangle;
        if(rectangle.Width<1 || rectangle.Height<1 || rectangle.Width>8192 || rectangle.Height>8192 || rectangle.Width*rectangle.Height>32000000)throw new Exception("Window dimensions outside capture limits");
        int width=(int)rectangle.Width,height=(int)rectangle.Height;
        using(var bitmap=new Bitmap(width,height)) {
            using(var graphics=Graphics.FromImage(bitmap)) {
                IntPtr dc=graphics.GetHdc();try {
                    if(!PrintWindow(new IntPtr(c.NativeWindowHandle),dc,2))throw new Exception("Window screenshot provider failed");
                }finally{graphics.ReleaseHdc(dc);}
            }
            string name="screen-"+(index+1).ToString("D3")+"-"+ordinal+".png";
            byte[] data;using(var buffer=new MemoryStream()){bitmap.Save(buffer,ImageFormat.Png);data=buffer.ToArray();}
            if(data.Length>16*1024*1024 || ImageBytes+data.Length>128*1024*1024)throw new Exception("Screenshot limit");
            ImageBytes+=data.Length;File.WriteAllBytes(Path.Combine(Folder,name),data);
            return Obj("name",name,"sha256",Hash(data),"bytes",data.Length,"width",width,"height",height);
        }
    }
    static void Snapshot(int index,string label) {
        var controls=new List<object>();var images=new List<object>();
        foreach(var e in Elements()) {
            try {
                var c=e.Current;string value="";object pattern;
                if(c.IsPassword)value="[redacted]";
                else if(e.TryGetCurrentPattern(ValuePattern.Pattern,out pattern))value=((ValuePattern)pattern).Current.Value;
                else if(e.TryGetCurrentPattern(TextPattern.Pattern,out pattern))value=((TextPattern)pattern).DocumentRange.GetText(1000);
                string name=c.Name ?? "";if(name.Length>1000)name=name.Substring(0,1000);if(value.Length>1000)value=value.Substring(0,1000);
                controls.Add(Obj("name",name,"automationId",c.AutomationId,"controlType",c.ControlType.ProgrammaticName,
                    "value",value,"enabled",c.IsEnabled,"offscreen",c.IsOffscreen));
            }catch(ElementNotAvailableException){}
        }
        int ordinal=0;
        foreach(var w in Windows()) {
            if(ordinal>=8){Unknowns.Add("window-count-limit");break;}
            try{images.Add(Screen(w,index,ordinal++));}
            catch(Exception ex){Unknowns.Add("screenshot-unavailable");images.Add(Obj("error",ex.Message));}
        }
        var state=Obj("elements",controls);
        States.Add(Obj("step",index,"label",label,"state",state,"stateSha256",Hash(Encoding.UTF8.GetBytes(Json.Serialize(state))),"images",images));Save();
    }
    [STAThread] static int Main(string[] args) {
        Output=args[1];Folder=Path.GetDirectoryName(Output);
        var input=(Dictionary<string,object>)Json.DeserializeObject(File.ReadAllText(args[0]));
        PidsFile=Str(input,"pidsFile");
        Result=Obj("driver","windows","complete",false,"steps",Steps,"states",States,"unknowns",Unknowns);
        try {
            var timer=Stopwatch.StartNew();while(Windows().Count==0){if(timer.ElapsedMilliseconds>10000)throw new Exception("No owned window appeared");Thread.Sleep(100);}
            int settle=Num(input,"settleMs",500);Thread.Sleep(settle);Snapshot(-1,"initial");
            var steps=(object[])input["steps"];
            for(int i=0;i<steps.Length;i++) {
                var step=(Dictionary<string,object>)steps[i];string action=Str(step,"action");
                var row=Obj("index",i,"action",action,"selector",step.ContainsKey("selector")?step["selector"]:"","status","running");Steps.Add(row);Save();
                try {
                    if(action=="wait")Thread.Sleep(Num(step,"ms",100));
                    else if(action!="snapshot") {
                        var selector=(Dictionary<string,object>)step["selector"];
                        var e=Find(selector,Num(step,"timeoutMs",5000));
                        if(!e.Current.IsEnabled)throw new Exception("Control is disabled");
                        object pattern;
                        if(action=="click") {
                            if(!e.TryGetCurrentPattern(InvokePattern.Pattern,out pattern))throw new Exception("Invoke pattern unavailable");
                            ((InvokePattern)pattern).Invoke();
                        }else if(action=="fill") {
                            if(e.Current.IsPassword)throw new Exception("Recorded password input is unsupported");
                            if(!e.TryGetCurrentPattern(ValuePattern.Pattern,out pattern))throw new Exception("Value pattern unavailable");
                            ((ValuePattern)pattern).SetValue(Str(step,"text"));
                            if(((ValuePattern)pattern).Current.Value!=Str(step,"text"))throw new Exception("The control did not retain the requested value");
                        }else if(action=="toggle") {
                            if(!e.TryGetCurrentPattern(TogglePattern.Pattern,out pattern))throw new Exception("Toggle pattern unavailable");
                            ((TogglePattern)pattern).Toggle();
                        }else if(action=="select") {
                            if(!e.TryGetCurrentPattern(SelectionItemPattern.Pattern,out pattern))throw new Exception("Selection pattern unavailable");
                            ((SelectionItemPattern)pattern).Select();
                        }else if(action=="assertText") {
                            var deadline=Stopwatch.StartNew();
                            while(true){
                                string name=e.Current.Name ?? "",value="";
                                if(!e.Current.IsPassword && e.TryGetCurrentPattern(ValuePattern.Pattern,out pattern))value=((ValuePattern)pattern).Current.Value;
                                if((name+"\n"+value).Contains(Str(step,"text")))break;
                                if(deadline.ElapsedMilliseconds>Num(step,"timeoutMs",5000))throw new Exception("Text assertion timed out");
                                Thread.Sleep(100);
                            }
                        }
                    }
                    Thread.Sleep(settle);Snapshot(i,Str(step,"label",action));row["status"]="passed";Save();
                }catch(Exception ex){row["status"]="failed";row["error"]=ex.Message;Snapshot(i,"failure");throw;}
            }
            Result["complete"]=Unknowns.Count==0;Save();return 0;
        }catch(Exception ex){Result["error"]=ex.Message;Save();return 1;}
    }
}
