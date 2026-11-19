// C ABI for the Python host. All registry, MCP and conversation execution is native SDK code.
#include <cymcp/ai.hpp>
#include <cymcp/mcp.hpp>
#include <cymcp/changes.hpp>
#include <cymcp/performance.hpp>
#include <cymcp/search.hpp>
#include <cstring>
#include <limits>
#include <unordered_map>
#ifdef _WIN32
#include <windows.h>
#include <dbghelp.h>
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
using namespace cymcp;
using Host = const char* (*)(const char*);
#if defined(_WIN32) && defined(CYDEC_NATIVE_DIAGNOSTICS)
static LONG WINAPI native_trace(EXCEPTION_POINTERS* exception) {
    const char* target=std::getenv("CYDEC_NATIVE_TRACE_FILE");
    if(!target || exception->ExceptionRecord->ExceptionCode!=EXCEPTION_ACCESS_VIOLATION)return EXCEPTION_CONTINUE_SEARCH;
    FILE* f=nullptr;fopen_s(&f,target,"a");if(!f)return EXCEPTION_CONTINUE_SEARCH;
    auto process=GetCurrentProcess();SymInitialize(process,nullptr,TRUE);
    CONTEXT context=*exception->ContextRecord;STACKFRAME64 frame{};
    frame.AddrPC.Offset=context.Rip;frame.AddrPC.Mode=AddrModeFlat;
    frame.AddrStack.Offset=context.Rsp;frame.AddrStack.Mode=AddrModeFlat;
    frame.AddrFrame.Offset=context.Rbp;frame.AddrFrame.Mode=AddrModeFlat;
    for(int i=0;i<32;++i){
        char data[sizeof(SYMBOL_INFO)+512]{};auto* symbol=reinterpret_cast<SYMBOL_INFO*>(data);symbol->SizeOfStruct=sizeof(SYMBOL_INFO);symbol->MaxNameLen=511;DWORD64 displacement=0;
        IMAGEHLP_MODULE64 module{};module.SizeOfStruct=sizeof(module);SymGetModuleInfo64(process,frame.AddrPC.Offset,&module);
        if(SymFromAddr(process,frame.AddrPC.Offset,&displacement,symbol))fprintf(f,"%s!%s+%llu\n",module.ModuleName,symbol->Name,displacement);
        else fprintf(f,"%s+%llx\n",module.ModuleName,frame.AddrPC.Offset-module.BaseOfImage);
        if(!StackWalk64(IMAGE_FILE_MACHINE_AMD64,process,GetCurrentThread(),&frame,&context,nullptr,SymFunctionTableAccess64,SymGetModuleBase64,nullptr))break;
    }
    fclose(f);return EXCEPTION_CONTINUE_SEARCH;
}
#endif
struct Bridge {
    Host host;
    Json options;
    std::shared_ptr<Registry> registry;
    std::shared_ptr<ResourceRegistry> resources;
    std::shared_ptr<ChangeFeed> changes;
    std::shared_ptr<PerformanceMonitor> performance;
    std::unique_ptr<ToolGateway> gateway;
    std::unique_ptr<McpServer> full, compact;
    ProviderRegistry providers;
    std::mutex mutex;
    std::map<std::string,Cancellation> active;
    std::map<std::string,std::shared_ptr<Conversation>> conversations;
    std::map<std::string,std::shared_ptr<McpClient>> remotes;
    std::unique_ptr<LocalHttpServer> http;
    std::unique_ptr<FileSearch> file_search;

    Json callback(const std::string& type, const Json& payload, const CallContext& c={}) {
        Json request={{"type",type},{"payload",payload},{"principal",c.principal},{"requestId",c.request_id},{"scope",c.transport_scope}};
        const auto cancellation_id=type=="invoke"?"host-"+random_token(16):std::string();
        struct Cleanup {
            Bridge* owner;std::string id;
            ~Cleanup(){if(!id.empty()){std::lock_guard lock(owner->mutex);owner->active.erase(id);}}
        } cleanup{this,cancellation_id};
        if(!cancellation_id.empty()){
            std::lock_guard lock(mutex);active[cancellation_id]=c.cancellation;
            request["cancellationId"]=cancellation_id;
        }
        const char* raw=host(request.dump().c_str());
        if(!raw) throw Error("HostError","Host returned no response");
        auto response=parse_json(raw,provider_message_limit);
        if(response.contains("error")) {
            auto e=response.at("error");
            throw Error(e.value("code",std::string("HostError")), e.value("message",std::string("Host operation failed")));
        }
        return response.value("result",Json::object());
    }
    explicit Bridge(Host callback,Json settings):host(callback),options(std::move(settings)) {
        changes=std::make_shared<ChangeFeed>();
        auto policy=Policy([this](const CallContext& c,const std::string& name,const Json& a){
            return this->callback("authorize",{{"name",name},{"arguments",a}},c).value("allowed",false)?Decision::allow:Decision::deny;
        });
        registry=std::make_shared<Registry>(policy);
        ResourceOptions ro;
        ro.chunk_bytes=options.value("chunkBytes",32768);
        ro.max_stored_bytes=options.value("memoryBytes",16*1024*1024);
        ro.max_disk_bytes=options.value("diskBytes",128*1024*1024);
        ro.result_ttl=std::chrono::milliseconds(options.value("retentionSeconds",900)*1000);
        if(options.value("diskSpool",true)) ro.disk_directory=std::filesystem::u8path(options.at("spoolDirectory").get<std::string>());
        resources=std::make_shared<ResourceRegistry>(policy,ro);
        if(options.value("notifications",true)) {
            registry->set_change_feed(changes);resources->set_change_feed(changes);
        }
        if(options.value("telemetry",false)) {
            PerformanceOptions po;
            if(options.contains("metricsFile"))po.jsonl_file=std::filesystem::u8path(options.at("metricsFile").get<std::string>());
            performance=std::make_shared<PerformanceMonitor>(po);
            registry->set_performance_monitor(performance);
        }
        ToolGatewayOptions go;go.resources=ro;go.inline_bytes=options.value("inlineBytes",16384);
        gateway=std::make_unique<ToolGateway>(registry,go,resources);
        McpServerOptions mo;mo.page_size=options.value("cataloguePageSize",512);mo.resources=resources;mo.changes=options.value("notifications",true)?changes:nullptr;
        mo.performance=performance;mo.cache_ttl=std::chrono::milliseconds(options.value("cacheTtlMs",30000));
        full=std::make_unique<McpServer>(*registry,"CyDecompilator",mo);
        compact=std::make_unique<McpServer>(*gateway->tools(),"CyDecompilator",mo);
    }
    CallContext context(const Json& p) {
        CallContext c;c.principal=p.value("principal",std::string("local"));
        c.request_id=p.value("requestId",std::string()); c.performance=performance;
        c.transport_scope=p.value("scope",std::string("host"));
        if(!c.request_id.empty()) {std::lock_guard lock(mutex); c.cancellation=active.try_emplace(c.request_id).first->second;}
        const auto timeout=p.value("timeoutMs",0LL);
        if(timeout>0)c.cancellation.deadline=Clock::now()+std::chrono::milliseconds(timeout);
        c.events=[this,c](const Event& e){ callback("event",{{"type",e.type},{"data",e.data}},c); };
        if(p.value("notifications",false))c.notifications=[this,c](const Json& notification){callback("notification",notification,c);};
        return c;
    }
    ProviderConfig provider_config(const Json& p,bool tools) {
        ProviderConfig cfg;cfg.settings=p.value("settings",Json::object());cfg.api_key=p.value("apiKey",std::string());
        cfg.process.executable=std::filesystem::u8path(p.value("executable",std::string()));
        cfg.process.arguments=p.value("arguments",std::vector<std::string>());
        if(p.contains("workingDirectory"))cfg.process.cwd=std::filesystem::u8path(p.at("workingDirectory").get<std::string>());
        if(tools) {
            if(p.contains("allowedTools")) {
                auto selected=std::make_shared<Registry>(Policy::allow_all());
                for(const auto& name:p.at("allowedTools")) {
                    const auto spec=registry->describe(name.get<std::string>());
                    Operation op;op.name=spec.at("name");op.description=spec.at("description");
                    op.input_schema=spec.at("inputSchema");op.output_schema=spec.value("outputSchema",Json::object());
                    op.read_only=spec.value("annotations",Json::object()).value("readOnlyHint",false);
                    op.handler=[this,n=op.name](const Json& a,const CallContext& c){return registry->invoke(n,a,c);};
                    selected->add(std::move(op));
                }
                if(options.value("compactDiscovery",true)) {
                    ToolGatewayOptions go;go.inline_bytes=options.value("inlineBytes",16384);
                    cfg.tools=ToolGateway(selected,go,resources).tools();
                } else cfg.tools=selected;
            } else cfg.tools=registry;
        }
        cfg.approvals=Policy::deny_all(); // Provider shell/file permissions never inherit host business permissions.
        return cfg;
    }
    Json dispatch(const Json& p) {
        std::string command=p.at("command");
        if(command=="info")return {{"version",version},{"revision",CYDEC_SDK_REVISION},{"modules",{"Core","Platform","Http","MCP","AI"}},{"chatUI",false}};
        if(command=="validate"){validate(p.at("value"),p.at("schema"));return p.at("value");}
        if(command=="register") {
            const auto& s=p.at("operation");Operation o;
            o.name=s.at("name");o.description=s.at("description");o.input_schema=s.at("inputSchema");
            o.output_schema=s.value("outputSchema",Json{{"type","object"}});o.read_only=s.value("readOnly",false);
            o.handler=[this,name=o.name](const Json& a,const CallContext& c){return callback("invoke",{{"name",name},{"arguments",a}},c);};
            registry->add(std::move(o));return {{"registered",true}};
        }
        if(command=="describe")return p.contains("name")?registry->describe(p.at("name")):registry->describe();
        if(command=="cancel") {std::lock_guard lock(mutex);auto it=active.find(p.at("id"));if(it!=active.end())it->second.cancel();return {{"cancelled",it!=active.end()}};}
        if(command=="releaseRequest") {std::lock_guard lock(mutex);active.erase(p.at("id"));return Json::object();}
        if(command=="checkCancellation") {std::lock_guard lock(mutex);auto it=active.find(p.at("id"));if(it==active.end())throw Error("InvalidState","Host invocation ended");it->second.check();return {{"active",true}};}
        auto c=context(p);
        if(command=="app")return dispatch_app(*registry,p.at("request"),c);
        if(command=="invoke")return registry->invoke(p.at("name"),p.value("arguments",Json::object()),c);
        if(command=="mcp")return (p.value("compact",false)?compact:full)->handle(p.at("request"),c);
        if(command=="resource") {
            Resource r;r.uri=p.at("uri");r.name=p.value("name",r.uri);r.description=p.value("description",std::string());
            r.mime_type=p.value("mimeType",std::string("text/plain"));
            auto text=std::make_shared<const std::string>(p.at("text").get<std::string>());r.size=text->size();
            r.cache_ttl=std::chrono::milliseconds(options.value("cacheTtlMs",30000));
            r.read=[text](std::size_t off,std::size_t len,const CallContext&){return off>=text->size()?std::string():text->substr(off,len);};
            resources->replace(std::move(r));return {{"registered",true}};
        }
        if(command=="store")return resources->store(p.at("text"),p.value("mimeType",std::string("application/json")),c);
        if(command=="read")return resources->read(p.at("uri"),c);
        if(command=="grep")return resources->grep(p.at("text"),p.value("ignoreCase",false),p.value("cursor",std::string()),c);
        if(command=="fileGrep" || command=="fileRead") {
            if(!options.value("ripgrep",false))throw Error("NotConfigured","Native workspace search is disabled; the host must explicitly choose its root.");
            {std::lock_guard lock(mutex);if(!file_search) {
                FileSearchOptions fo;fo.root=std::filesystem::u8path(options.at("workspaceRoot").get<std::string>());fo.ripgrep=find_executable("rg");
                if(fo.ripgrep.empty())throw Error("MissingDependency","Install ripgrep separately or disable native workspace search.");
                file_search=std::make_unique<FileSearch>(fo);
            }}
            return command=="fileGrep"?file_search->grep(p.at("arguments"),c):file_search->read(p.at("arguments"),c);
        }
        if(command=="stats")return {{"storage",resources->storage_stats()},{"performance",performance?performance->snapshot():Json::object()},{"changes",changes->sequence()}};
        if(command=="publishChange"){changes->publish(p.value("topic",std::string("resources")),p.value("uri",std::string()));return {{"sequence",changes->sequence()}};}
        if(command=="providers")return providers.describe();
        if(command=="discover") {
            DiscoveryOptions d;d.probe_local_services=p.value("probeLocal",true);
            const auto configured=p.value("configured",Json::object());
            for(const auto& entry:configured.items())d.configured[entry.key()]=provider_config(entry.value(),false);
            Json result=Json::array();
            for(const auto& x:providers.discover(d,c))result.push_back({{"id",x.provider_id},{"name",x.name},{"state",x.state},{"source",x.source},{"errorCode",x.error_code},{"models",x.models},{"executable",path_utf8(x.config.process.executable)}});
            return result;
        }
        if(command=="models") {
            auto provider=providers.create(p.at("provider"),provider_config(p,false));provider->connect(c);
            try {auto result=provider->list_models(c);provider->disconnect();return result;}
            catch(...){provider->disconnect();throw;}
        }
        if(command=="conversationOpen") {
            std::string id=p.at("id");auto provider=providers.create(p.at("provider"),provider_config(p,p.value("tools",false)));
            auto conversation=std::make_shared<Conversation>(provider,p.value("model",std::string()),p.value("system",std::string()));
            ContextOptions co;co.max_bytes=provider->uses_host_history()&&!provider->uses_native_turn_context()?p.value("contextBytes",0):0;co.recent_turns=p.value("recentTurns",8);conversation->configure_context(co);
            if(p.contains("checkpoint"))conversation->restore(p.at("checkpoint"),c);
            else if(p.contains("history") && provider->uses_host_history()) {
                Json messages=Json::array();auto system=p.value("system",std::string());
                if(!system.empty())messages.push_back({{"role","system"},{"content",system}});
                for(const auto& message:p.at("history"))messages.push_back(message);
                Json snapshot={{"format","cymcp-conversation"},{"version",1},{"provider",p.at("provider")},{"history_mode","host"},{"session",{{"id",""},{"model",p.value("model",std::string())}}},{"model",p.value("model",std::string())},{"messages",messages}};
                conversation->restore(snapshot,c);
            } else conversation->connect(p.value("nativeId",std::string()),c,p.value("automaticModel",false));
            {std::lock_guard lock(mutex);if(conversations.count(id))throw Error("Conflict","Conversation already open");conversations[id]=conversation;}
            return {{"status",conversation->status()},{"sessionId",conversation->session().id}};
        }
        if(command.starts_with("conversation")) {
            std::shared_ptr<Conversation> conversation;
            {std::lock_guard lock(mutex);conversation=conversations.at(p.at("id"));}
            if(command=="conversationSend") {
                auto result=conversation->send(p.at("content"),c);
                return {{"text",result.text},{"finishReason",result.finish_reason},{"usage",result.usage},{"metrics",result.metrics},{"nativeId",conversation->session().id},{"model",conversation->session().model}};
            }
            if(command=="conversationCancel"){conversation->cancel();return {{"cancelled",true}};}
            if(command=="conversationCheckpoint")return conversation->checkpoint();
            if(command=="conversationHistory")return conversation->history();
            if(command=="conversationClose"){conversation->disconnect();std::lock_guard lock(mutex);conversations.erase(p.at("id"));return Json::object();}
        }
        if(command=="remoteConnect") {
            auto cfg=p.at("config");McpClientOptions opts;
            opts.max_cache_ttl=std::chrono::milliseconds(options.value("cacheTtlMs",30000));opts.performance=performance;
            if(!options.value("cache",true)){opts.cache_entries=0;opts.cache_bytes=0;}
            std::shared_ptr<McpClient> client;
            if(cfg.contains("url"))client=std::make_shared<McpClient>(cfg.at("url").get<std::string>(),p.value("token",std::string()),opts);
            else {ProcessOptions po;po.executable=std::filesystem::u8path(cfg.at("executable").get<std::string>());po.arguments=cfg.value("arguments",std::vector<std::string>());if(cfg.contains("workingDirectory"))po.cwd=std::filesystem::u8path(cfg.at("workingDirectory").get<std::string>());
                // An application client credential must not accidentally authenticate
                // a different child server. Only its explicitly selected vault token does.
                po.environment["CYMCP_TOKEN"]=p.value("token",std::string());po.environment["CYTOOLS_TOKEN"]=p.value("token",std::string());
                client=std::make_shared<McpClient>(po,opts);}
            client->connect(c.cancellation);auto tools=client->list_tools(c.cancellation);
            {std::lock_guard lock(mutex);remotes[p.at("id")]=client;}return tools;
        }
        if(command.starts_with("remote")) {
            std::shared_ptr<McpClient> client;{std::lock_guard lock(mutex);client=remotes.at(p.at("id"));}
            if(command=="remoteCall")return client->call_tool(p.at("name"),p.value("arguments",Json::object()),c.cancellation);
            if(command=="remoteTools")return client->list_tools_page(p.contains("cursor")?std::optional<std::string>(p.at("cursor")):std::nullopt,c.cancellation);
            if(command=="remoteResources")return client->list_resources(c.cancellation);
            if(command=="remoteRead")return client->read_resource(p.at("uri"),c.cancellation);
            if(command=="remoteCacheStats"){auto s=client->cache_stats();return {{"hits",s.hits},{"misses",s.misses},{"entries",s.entries},{"bytes",s.bytes}};}
            if(command=="remoteRefresh"){client->clear_cache();return client->list_tools(c.cancellation);}
            if(command=="remoteNotifications"){if(p.value("start",false))client->start_notifications({{"toolsListChanged",true},{"resourcesListChanged",true}},c.cancellation);return {{"status",client->notification_status()},{"events",client->drain_notifications()}};}
            if(command=="remoteClose"){std::lock_guard lock(mutex);remotes.erase(p.at("id"));return Json::object();}
        }
        throw Error("UnknownMethod","Unknown native bridge command");
    }
};
API void* cydec_create(Host callback,const char* config) noexcept {
    #if defined(_WIN32) && defined(CYDEC_NATIVE_DIAGNOSTICS)
    static std::once_flag trace_once;
    std::call_once(trace_once,[]{if(std::getenv("CYDEC_NATIVE_TRACE_FILE"))AddVectoredExceptionHandler(1,native_trace);});
    #endif
    try {return new Bridge(callback,parse_json(config));}catch(...){return nullptr;}
}
API void cydec_destroy(void* handle) noexcept {delete static_cast<Bridge*>(handle);}
API char* cydec_call(void* handle,const char* request) noexcept {
    Json response;
    try {response={{"result",static_cast<Bridge*>(handle)->dispatch(parse_json(request,provider_message_limit))}};}
    catch(const Error& e){response={{"error",{{"code",e.code},{"message",redact_error_message(e.what())}}}};}
    catch(const std::exception& e){response={{"error",{{"code","NativeError"},{"message",redact_error_message(e.what())}}}};}
    catch(...){response={{"error",{{"code","NativeError"},{"message","Native operation failed"}}}};}
    const auto text=response.dump();auto* buffer=new char[text.size()+1];std::memcpy(buffer,text.c_str(),text.size()+1);return buffer;
}
API void cydec_free(char* buffer) noexcept {delete[] buffer;}
