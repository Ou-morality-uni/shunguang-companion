import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, AudioLines, Bell, Check, Cpu, Heart, LoaderCircle, Play, ShieldCheck, WandSparkles, Wrench } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { request, type Conversation, type Features, type ModelSettings, type Provider, type InspectedVoiceReference } from './api';
import { MemorySpace, VoiceConsole, type Panel } from './Spaces';
import { useCompanionAudio } from './useAudioQueue';
import { ToolFeedback } from './Evidence';

const categories=[{id:'model',label:'模型连接',icon:Cpu},{id:'voice',label:'声音与播放',icon:AudioLines},{id:'effects',label:'沉浸光效',icon:WandSparkles},{id:'tools',label:'工具服务',icon:Wrench},{id:'memory',label:'长期记忆',icon:Heart},{id:'reminders',label:'关怀提醒',icon:Bell}] as const;
const cloneModel='mimo-v2.5-tts-voiceclone';
const defaultReferencePath='source/resources/voice/ye-shunguang/reference-original.mp3';
function editableFeatures(value:Features):Features {
  return {...value,tts:{...value.tts,model:value.tts.provider==='mimo'?cloneModel:value.tts.model,voice:'',reference_path:value.tts.reference_path||defaultReferencePath}};
}
function voiceSignature(value:Features['tts']|undefined){return JSON.stringify(value?[value.provider,value.base_url,value.model,value.voice,value.enabled,value.auto_play,value.use_model_key,value.speed,value.timeout,value.style,value.reference_path||defaultReferencePath,value.reference_id,value.reference_sha256,value.external_reference_enabled]:[]);}
type Props={panel:Panel;setPanel:(value:Panel)=>void;settings:ModelSettings|null;features:Features|null;effects:boolean;setEffects:(value:boolean)=>void;reduceMotion:boolean;setReduceMotion:(value:boolean)=>void;onModelSaved:(value:ModelSettings)=>void;onFeaturesSaved:(value:Features)=>void;conversations:Conversation[];active:string|null;onMemoryChanged:()=>void;onTestReminder:()=>void};
function Toggle({label,description,checked,onChange}:{label:string;description?:string;checked:boolean;onChange:(value:boolean)=>void}) {return <div className="setting-toggle"><div><strong>{label}</strong>{description&&<p>{description}</p>}</div><Switch aria-label={label} checked={checked} onCheckedChange={onChange}/></div>;}

export function CompanionSettings({panel,setPanel,settings,features,effects,setEffects,reduceMotion,setReduceMotion,onModelSaved,onFeaturesSaved,conversations,active,onMemoryChanged,onTestReminder}:Props) {
  const [draft,setDraft]=useState<ModelSettings|null>(settings),[featureDraft,setFeatureDraft]=useState<Features|null>(features),[providers,setProviders]=useState<Provider[]>([]),[ttsProviders,setTtsProviders]=useState<Provider[]>([]),[models,setModels]=useState<Array<{id:string}>>([]),[ttsModels,setTtsModels]=useState<Array<{id:string}>>([]),[referenceInfo,setReferenceInfo]=useState<InspectedVoiceReference|null>(null),[referenceBusy,setReferenceBusy]=useState(false);
  const [modelKey,setModelKey]=useState(''),[voiceKey,setVoiceKey]=useState(''),[toolKey,setToolKey]=useState(''),[clearModelKey,setClearModelKey]=useState(false),[clearVoiceKey,setClearVoiceKey]=useState(false),[clearToolKey,setClearToolKey]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
  const opened=useRef(false),audio=useCompanionAudio(),navRefs=useRef<Array<HTMLButtonElement|null>>([]);
  const returningFocus=useRef<HTMLElement|null>(null),mobileCategory=useRef<HTMLSelectElement|null>(null),requestLock=useRef(false);
  const referenceFileInput=useRef<HTMLInputElement|null>(null),referenceLock=useRef(false);
  const panelRef=useRef(panel);panelRef.current=panel;
  const [profiles,setProfiles]=useState<Array<ModelSettings&{id:string}>>([]);
  const [toolTestQuery,setToolTestQuery]=useState('Python programming language'),[toolTestResult,setToolTestResult]=useState<Record<string,unknown>|null>(null);
  async function testSearch(){
    if(requestLock.current||!toolTestQuery.trim())return;
    requestLock.current=true;setBusy(true);setToolTestResult(null);setNotice('正在使用已保存配置测试一次搜索…');
    try{const result=await request<Record<string,unknown>>('/tools/run',{method:'POST',body:JSON.stringify({name:'web_search',args:{query:toolTestQuery.trim(),limit:3}})});setToolTestResult(result);setNotice(result.ok?'搜索返回真实来源，请打开核对。':typeof result.message==='string'?result.message:'搜索未取得可用结果，请检查已保存的服务配置。');}
    catch(e){setNotice((e as Error).message);}
    finally{requestLock.current=false;setBusy(false);}
  }
  async function activateProfile(id:string){if(!id)return;setBusy(true);try{const value=await request<ModelSettings>('/providers/activate',{method:'POST',body:JSON.stringify({id})});setDraft(value);onModelSaved(value);setModelKey('');setClearModelKey(false);setModels([]);setNotice('已切换到保存的连接。');}catch(e){setNotice((e as Error).message);}finally{requestLock.current=false;setBusy(false);}}
  useEffect(()=>{
    if(panel&&!opened.current){opened.current=true;setDraft(settings?{...settings}:null);setFeatureDraft(features?editableFeatures(structuredClone(features)):null);setModelKey('');setVoiceKey('');setToolKey('');setClearModelKey(false);setClearVoiceKey(false);setClearToolKey(false);setNotice('');setReferenceInfo(null);
      const calls=[request<Provider[]>('/providers/presets').then(setProviders),request<Provider[]|{presets:Provider[]}>('/tts/presets').then(data=>setTtsProviders(Array.isArray(data)?data:data.presets)),request<Features>('/features').then(value=>setFeatureDraft(editableFeatures(value))),request<Array<ModelSettings&{id:string}>>('/providers/profiles').then(setProfiles)];
      void Promise.allSettled(calls).then(results=>{const failed=results.filter(item=>item.status==='rejected');if(failed.length&&panelRef.current)setNotice('部分设置暂时无法读取，请确认后端服务在线。');});
    }else if(!panel){opened.current=false;setModelKey('');setVoiceKey('');setToolKey('');setReferenceInfo(null);}
  },[panel,settings,features]);
  function setTts(update:Partial<Features['tts']>){setFeatureDraft(previous=>previous?{...previous,tts:{...previous.tts,...update}}:previous);}
  function setTools(update:Partial<Features['tools']>){if(featureDraft)setFeatureDraft({...featureDraft,tools:{...featureDraft.tools,...update}});}
  function setReminder(update:Partial<Features['reminders']>){if(featureDraft)setFeatureDraft({...featureDraft,reminders:{...featureDraft.reminders,...update}});}
  async function discoverModels(){if(!draft||busy||requestLock.current)return;requestLock.current=true;setBusy(true);setNotice('正在读取提供商真实模型列表…');try{const result=await request<{models:Array<{id:string}>;notice?:string}>('/providers/discover',{method:'POST',body:JSON.stringify({provider:draft.provider||'custom',protocol:draft.protocol||'openai',base_url:draft.base_url,timeout:draft.timeout,api_key:modelKey.trim()||undefined})});setModels(result.models);setNotice(result.notice||`读取到 ${result.models.length} 个模型；请选择或手动填写模型 ID。`);}catch(e){setNotice(`${(e as Error).message} 可手动填写模型 ID。`);}finally{requestLock.current=false;setBusy(false);}}
  async function discoverVoice(){
    if(!featureDraft||busy||requestLock.current)return;
    if(featureDraft.tts.provider!=='mimo'){setNotice('当前提供商不支持本项目的本地参考声音克隆，请选择小米 MiMo。');return;}
    requestLock.current=true;setBusy(true);setNotice('正在读取支持本地参考音频的克隆模型…');
    try{
      const result=await request<{models:Array<{id:string}>;capabilities?:{reference_audio?:boolean};notice?:string}>('/tts/discover',{method:'POST',body:JSON.stringify({provider:featureDraft.tts.provider,base_url:featureDraft.tts.base_url,model:cloneModel,voice:'',use_model_key:featureDraft.tts.use_model_key,api_key:voiceKey.trim()||undefined})});
      const supported=result.models.filter(item=>item.id===cloneModel);
      setTtsModels(supported);
      setNotice(supported.length?'已发现 MiMo 参考声音克隆模型。请选择本地 MP3、保存配置后测试。':'上游未列出参考声音克隆模型。保留模型 ID 供权限核对，不回退到预置音色。');
    }catch(e){setNotice(`${(e as Error).message} 不会回退到普通 TTS 或预置音色。`);}
    finally{requestLock.current=false;setBusy(false);}
  }
  async function saveModel(test=false){if(!draft||requestLock.current)return;requestLock.current=true;setBusy(true);setNotice('');try{const value=await request<ModelSettings>('/settings',{method:'PATCH',body:JSON.stringify({provider:draft.provider||'custom',protocol:draft.protocol||'openai',base_url:draft.base_url,model:draft.model,temperature:draft.temperature,timeout:draft.timeout,api_key:modelKey.trim()||undefined,clear_api_key:clearModelKey})});setDraft(value);onModelSaved(value);setModelKey('');setClearModelKey(false);setNotice('模型配置已保存。');setProfiles(await request<Array<ModelSettings&{id:string}>>('/providers/profiles'));if(test){const result=await request<{message:string}>('/providers/test',{method:'POST'});setNotice(`真实连接测试成功：${result.message}`);}}catch(e){setNotice((e as Error).message);}finally{requestLock.current=false;setBusy(false);}}
  async function saveFeature(section:'tts'|'tools'|'reminders'){
    if(!featureDraft||requestLock.current||referenceLock.current)return;
    requestLock.current=true;setBusy(true);setNotice('');
    try{
      let body:Record<string,unknown>={...featureDraft[section]};
      delete body.has_api_key;delete body.capabilities;delete body.configured;delete body.notice;delete body.coverage;delete body.reference_sha256;
      if(section==='tts'){
        const current=featureDraft.tts;
        if(current.provider!=='mimo'||current.model!==cloneModel)throw new Error('当前提供商或模型不支持本地 MP3 参考声音克隆，请选择小米 MiMo 克隆模型。');
        const selected=await request<InspectedVoiceReference>('/voice/reference/inspect',{method:'POST',body:JSON.stringify({path:current.reference_path||defaultReferencePath})});
        if(selected.format!=='mp3')throw new Error('请选择 MP3 参考音频；不会使用预置音色替代。');
        setReferenceInfo(selected);
        body={enabled:!!current.enabled,auto_play:!!current.auto_play,muted:!!current.muted,provider:current.provider,base_url:current.base_url,model:cloneModel,voice:'',use_model_key:!!current.use_model_key,timeout:current.timeout??45,speed:current.speed??1,style:current.style||'',reference_path:selected.path,reference_id:selected.id,external_reference_enabled:!!current.external_reference_enabled,api_key:voiceKey.trim()||undefined,clear_api_key:clearVoiceKey};
      }
      if(section==='tools')body={...body,api_key:toolKey.trim()||undefined,clear_api_key:clearToolKey};
      const value=await request<Features>('/features',{method:'PATCH',body:JSON.stringify({[section]:body})});
      setFeatureDraft(editableFeatures(value));onFeaturesSaved(value);
      if(section==='tts'){setVoiceKey('');setClearVoiceKey(false);}
      if(section==='tools'){setToolKey('');setClearToolKey(false);}
      setNotice(section==='tts'?'克隆声音配置已保存。参考音频仅在允许外部处理并请求合成时发送。':'配置已保存。');
    }catch(e){setNotice((e as Error).message);}
    finally{requestLock.current=false;setBusy(false);}
  }
  async function inspectReference(){
    if(referenceLock.current)return;
    referenceLock.current=true;setReferenceBusy(true);setNotice('正在验证运行电脑上的 MP3，不会发送到外部服务…');
    try{
      const selected=await request<InspectedVoiceReference>('/voice/reference/inspect',{method:'POST',body:JSON.stringify({path:featureDraft?.tts.reference_path||defaultReferencePath})});
      if(selected.format!=='mp3')throw new Error('请选择 MP3 参考音频。');
      setReferenceInfo(selected);setTts({reference_path:selected.path,reference_id:selected.id,reference_sha256:selected.sha256});
      setNotice('已选择此 MP3，验证仅在本机完成。请保存配置后测试克隆声音。');
    }catch(e){setReferenceInfo(null);setNotice((e as Error).message);}
    finally{referenceLock.current=false;setReferenceBusy(false);}
  }
  async function uploadReference(file?:File){
    if(!file||referenceLock.current)return;
    if(file.size>6*1024*1024){setNotice('参考 MP3 需不超过 6 MB。');return;}
    if(!file.name.toLowerCase().endsWith('.mp3')){setNotice('请选择 MP3 参考音频。');return;}
    referenceLock.current=true;setReferenceBusy(true);setNotice('正在把所选 MP3 保存到运行服务的电脑，不会外传…');
    try{
      const audio_base64=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('无法读取 MP3 文件'));reader.readAsDataURL(file);});
      const uploaded=await request<InspectedVoiceReference>('/voice/references/upload',{method:'POST',body:JSON.stringify({name:file.name,format:'mp3',audio_base64})});
      if(!uploaded.path||!uploaded.id)throw new Error('上传结果缺少参考文件定位，请重试。');
      setTts({reference_path:uploaded.path,reference_id:uploaded.id,reference_sha256:uploaded.sha256});
      setReferenceInfo(uploaded);
      setNotice('MP3 已归档并自动选中。请保存配置后测试，无需再从列表选择。');
    }catch(e){setNotice((e as Error).message);}
    finally{referenceLock.current=false;setReferenceBusy(false);}
  }
  const tts=featureDraft?.tts,tools=featureDraft?.tools,reminders=featureDraft?.reminders;
  const referenceSupported=tts?.provider==='mimo'&&tts.model==='mimo-v2.5-tts-voiceclone';
  const cloneProviders=ttsProviders.filter(item=>item.id==='mimo'||item.reference_audio||item.reference_supported);
  const voiceDirty=voiceSignature(tts)!==voiceSignature(features?.tts)||!!voiceKey.trim()||clearVoiceKey;
  const savedCloneReady=features?.tts.provider==='mimo'&&features.tts.model===cloneModel&&!!features.tts.enabled&&!!features.tts.external_reference_enabled&&!!features.tts.reference_path;
  function testSavedClone(){
    if(voiceDirty){setNotice('参考文件或语音设置已修改，请先保存克隆配置，再测试已保存的声音。');return;}
    if(!savedCloneReady){setNotice('请先选择小米克隆模型、启用 TTS 和参考音频发送开关，并保存配置。');return;}
    audio.enqueue('你好，忙碌之余，也记得照顾好自己。','参考声音克隆测试');
  }
  function selectProvider(id:string){
    const item=providers.find(value=>value.id===id);if(!draft||!item)return;
    const stored=profiles.find(value=>value.base_url.replace(/\/$/,'')===item.base_url.replace(/\/$/,'')&&(value.protocol||'openai')===(item.protocol||'openai'));
    setDraft({...draft,provider:item.id,base_url:item.base_url,protocol:item.protocol||'openai',model:stored?.model||item.model||'',has_api_key:!!stored?.has_api_key});
    setModels([]);setModelKey('');setClearModelKey(false);
    setNotice(stored?.has_api_key?'已找到此服务保存的连接，留空使用此服务的已存密钥。':item.notice||'填写当前服务的密钥后读取真实模型，并选择模型 ID。');
  }
  return <Dialog open={!!panel} onOpenChange={open=>{if(!open)setPanel(null);}}><DialogContent className="settings-modal unified-settings" showCloseButton onOpenAutoFocus={e=>{e.preventDefault();returningFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;if(matchMedia('(max-width:700px)').matches)mobileCategory.current?.focus();else navRefs.current[Math.max(0,categories.findIndex(item=>item.id===panel))]?.focus();}} onCloseAutoFocus={e=>{e.preventDefault();returningFocus.current?.focus();}}><div className="modal-heading"><span className="eyebrow">YOUR COMPANION, YOUR WAY</span><DialogTitle>陪伴设置</DialogTitle><DialogDescription>把相伴的方式，调成你喜欢的样子。</DialogDescription></div><div className="settings-layout"><nav className="settings-nav" aria-label="设置分类" role="tablist" aria-orientation="vertical">{categories.map(({id,label,icon:Icon},index)=><button ref={el=>{navRefs.current[index]=el;}} id={`settings-tab-${id}`} type="button" role="tab" aria-selected={panel===id} aria-controls={`settings-body-${id}`} tabIndex={panel===id?0:-1} disabled={busy} key={id} className={panel===id?'active':''} onClick={()=>{setPanel(id);setNotice('');}} onKeyDown={e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();const next=(index+(e.key==='ArrowDown'?1:-1)+categories.length)%categories.length;setPanel(categories[next].id);setNotice('');navRefs.current[next]?.focus();}}}><Icon size={18}/>{label}</button>)}</nav><label className="mobile-settings-select">设置分类<select ref={mobileCategory} value={panel||'model'} disabled={busy} onChange={e=>{setPanel(e.target.value as Panel);setNotice('');}}>{categories.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select></label><section className="settings-body" role="tabpanel" id={`settings-body-${panel}`} aria-labelledby={`settings-tab-${panel}`} tabIndex={0}>
      {panel==='model'&&profiles.length>0&&<label className="field">已保存的连接<select aria-label="已保存的连接" value="" disabled={busy} onChange={e=>void activateProfile(e.target.value)}><option value="">选择并激活保存的连接</option>{profiles.map(item=><option key={item.id} value={item.id}>{item.provider||item.base_url} · {item.protocol||'openai'} · {item.model}</option>)}</select></label>}{panel==='model'&& (draft?<form onSubmit={e=>{e.preventDefault();void saveModel();}}><h2>模型连接</h2><label className="field">提供商<select aria-label="提供商" value={draft.provider||'custom'} onChange={e=>selectProvider(e.target.value)}>{providers.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}{!providers.some(item=>item.id===(draft.provider||'custom'))&&<option value={draft.provider||'custom'}>当前自定义配置</option>}</select></label><label className="field">接口协议<select aria-label="接口协议" value={draft.protocol||'openai'} onChange={e=>setDraft({...draft,protocol:e.target.value as 'openai'|'anthropic'})}><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic 兼容</option></select><span className="field-hint">协议决定请求和流式解析方式，请匹配提供商的实际接口。</span></label><label className="field">API 地址<Input aria-label="模型 API 地址" type="url" required value={draft.base_url} onChange={e=>setDraft({...draft,base_url:e.target.value,has_api_key:e.target.value===settings?.base_url&&!!settings.has_api_key})} maxLength={500}/></label><label className="field">API 密钥<Input aria-label="模型 API 密钥" type="password" autoComplete="off" spellCheck={false} value={modelKey} disabled={clearModelKey||busy} onChange={e=>setModelKey(e.target.value)} onBlur={()=>{if(modelKey.trim())void discoverModels();}} placeholder={clearModelKey?'保存后移除已存密钥':draft.has_api_key?'已保存当前服务密钥；留空保留，填写替换':'填写当前提供商的 API Key'} maxLength={2048}/><span className="field-hint">密钥由后端加密保存，已有密钥不会回显。</span></label>{draft.has_api_key&&<button className="clear-key" type="button" onClick={()=>{setClearModelKey(v=>!v);setModelKey('');}}>{clearModelKey?'取消移除密钥':'明确移除已保存密钥'}</button>}<div className="discovery-row"><Button type="button" variant="outline" disabled={busy||clearModelKey} onClick={()=>void discoverModels()}><SearchIcon/>读取可用模型</Button><span>无列表权限时可手动填写</span></div>{models.length>0&&<label className="field">可用模型<select value={models.some(item=>item.id===draft.model)?draft.model:''} onChange={e=>setDraft({...draft,model:e.target.value})}><option value="">选择实际模型</option>{models.map(item=><option key={item.id} value={item.id}>{item.id}</option>)}</select></label>}<label className="field">模型 ID<Input aria-label="模型 ID" required value={draft.model} onChange={e=>setDraft({...draft,model:e.target.value})} maxLength={150}/></label><div className="field-row"><label className="field">温度<Input type="number" min={0} max={2} step={.1} value={draft.temperature} onChange={e=>setDraft({...draft,temperature:Number(e.target.value)})}/></label><label className="field">超时（秒）<Input type="number" min={5} max={120} value={draft.timeout} onChange={e=>setDraft({...draft,timeout:Number(e.target.value)})}/></label></div><div className="key-note"><ShieldCheck size={19}/><p>调用会把对话和必要上下文发送给你选择的模型服务。密钥只用于该服务，不保存到浏览器。</p></div><div className="modal-actions"><Button type="button" variant="outline" disabled={busy||clearModelKey||!draft.model.trim()} onClick={()=>void saveModel(true)}><ArrowUpRight size={15}/>保存并测试连接</Button><Button type="submit" disabled={busy}><Check size={15}/>保存配置</Button></div></form>:<p>模型设置需要后端服务在线。</p>)}
      {panel==='voice'&&tts&&<form onSubmit={e=>{e.preventDefault();void saveFeature('tts');}}>
        <h2>声音与播放</h2>
        <p className="space-note">仅使用你选择的本地 MP3 克隆参考声音，不使用预置音色。</p>
        <Toggle label="开启 TTS" checked={!!tts.enabled} onChange={enabled=>setTts({enabled})}/>
        <Toggle label="自动朗读新回复" description="回复完整后按顺序加入播放队列；浏览器仍可能需要点击允许播放。" checked={!!tts.auto_play} onChange={auto_play=>setTts({auto_play})}/>
        <label className="field">语音提供商
          <select aria-label="语音提供商" value={tts.provider} onChange={e=>{
            const item=cloneProviders.find(value=>value.id===e.target.value);
            setTts({provider:e.target.value,base_url:item?.base_url||tts.base_url,model:cloneModel,voice:'',has_api_key:item?.base_url===features?.tts.base_url&&!!features?.tts.has_api_key});
            setVoiceKey('');setTtsModels([]);setNotice('已选择参考声音克隆提供商。请选择本地 MP3 并保存配置。');
          }}>
            {cloneProviders.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}
            {!cloneProviders.some(item=>item.id==='mimo')&&<option value="mimo">小米 MiMo · 参考声音克隆</option>}
            {tts.provider!=='mimo'&&!cloneProviders.some(item=>item.id===tts.provider)&&<option value={tts.provider}>{tts.provider}（不支持本项目的参考克隆）</option>}
          </select>
          <span className="field-hint">当前已适配小米 MiMo 的 MP3 参考声音克隆。其他服务未验证参考能力，不回退到预置音色。</span>
        </label>
        <label className="field">API 地址<Input aria-label="语音 API 地址" type="url" required value={tts.base_url} onChange={e=>setTts({base_url:e.target.value,has_api_key:e.target.value===features?.tts.base_url&&!!features?.tts.has_api_key})}/></label>
        <Toggle label="复用已保存的小米模型密钥" description="只在小米官方同地址接口复用后端保存的密钥。" checked={!!tts.use_model_key} onChange={use_model_key=>setTts({use_model_key})}/>
        <label className="field">语音 API 密钥<Input aria-label="语音 API 密钥" type="password" autoComplete="off" spellCheck={false} value={voiceKey} disabled={clearVoiceKey||busy} onChange={e=>setVoiceKey(e.target.value)} onBlur={()=>{if(voiceKey.trim())void discoverVoice();}} placeholder={tts.has_api_key?'已保存；留空保留，填写替换':'填写小米语音 API Key'} maxLength={2048}/></label>
        {tts.has_api_key&&<button className="clear-key" type="button" onClick={()=>{setClearVoiceKey(v=>!v);setVoiceKey('');}}>{clearVoiceKey?'取消移除密钥':'明确移除语音密钥'}</button>}
        <Button type="button" variant="outline" disabled={busy||clearVoiceKey||tts.provider!=='mimo'} onClick={()=>void discoverVoice()}><SearchIcon/>读取参考克隆模型</Button>
        {ttsModels.length>0&&<p className="space-note" role="status">已发现：{ttsModels.map(item=>item.id).join('、')}</p>}
        <label className="field">TTS 克隆模型 ID<Input aria-label="TTS 克隆模型 ID" readOnly value={tts.provider==='mimo'?cloneModel:tts.model}/><span className="field-hint">仅使用 mimo-v2.5-tts-voiceclone。</span></label>
        {!referenceSupported&&<p className="settings-notice" role="status">当前提供商或模型不支持本地参考声音克隆，请选择小米 MiMo；不会改用预置音色。</p>}
        <label className="field">语速<Input type="number" min={.25} max={4} step={.05} value={tts.speed??1} onChange={e=>setTts({speed:Number(e.target.value)})}/></label>
        <div className="reference-panel local-reference-picker">
          <h3>选择本地参考音频</h3>
          <label className="field">参考 MP3 路径<Input aria-label="参考 MP3 路径" disabled={busy||referenceBusy} required value={tts.reference_path??defaultReferencePath} onChange={e=>{setReferenceInfo(null);setTts({reference_path:e.target.value,reference_id:'',reference_sha256:undefined});}} placeholder={defaultReferencePath} maxLength={1200}/><span className="field-hint">相对路径从项目目录定位，也可填写运行服务电脑上的绝对路径。手机可用下方文件按钮选择 MP3。</span></label>
          <input ref={referenceFileInput} type="file" hidden accept=".mp3,audio/mpeg" aria-label="选择参考 MP3 文件" onChange={e=>{const file=e.target.files?.[0];e.target.value='';void uploadReference(file);}}/>
          <div className="inline-actions">
            <Button type="button" variant="outline" disabled={referenceBusy} onClick={()=>referenceFileInput.current?.click()}>选择 MP3 文件</Button>
            <Button type="button" variant="outline" disabled={referenceBusy||busy||!tts.reference_path?.trim()} onClick={()=>void inspectReference()}>验证电脑上的 MP3</Button>
          </div>
          <div className="reference-selected" role="status">
            {referenceBusy?<><LoaderCircle size={16} className="spin"/>正在本机登记 MP3…</>:referenceInfo?<><Check size={16}/><span>已选中：{referenceInfo.name}<small>{referenceInfo.format.toUpperCase()} · {(referenceInfo.bytes/1024/1024).toFixed(2)} MB{Number.isFinite(referenceInfo.duration)?` · ${referenceInfo.duration.toFixed(1)} 秒`:''}<br/>{referenceInfo.path}</small></span></>:<span>{tts.reference_id?'当前已保存的参考 MP3 路径':'路径已填写，验证或选择 MP3 后确认'}<small>{tts.reference_path||defaultReferencePath}</small></span>}
          </div>
          <p className="space-note">文件选择最多 6 MB。验证和文件归档仅在运行服务的电脑完成，不会发送外部服务。上传成功会自动选中，可再次选择同一文件。</p>
        </div>
        <Toggle label="允许合成时发送参考音频" description="默认关闭。仅当你开启并保存，所选 MP3 的完整音频会发送给小米，用于本次参考声音克隆；不会启动训练或购买服务。" checked={!!tts.external_reference_enabled} onChange={external_reference_enabled=>setTts({external_reference_enabled})}/>
        <VoiceConsole/>
        <p className="space-note">{voiceDirty?'参考文件或设置已修改，请先保存克隆配置。测试不会使用之前的普通 TTS 配置。':savedCloneReady?'测试会使用已保存的本地 MP3 参考声音克隆配置。':'请启用 TTS、选择 MP3 并开启参考音频发送开关，保存后才能测试克隆。'}</p>
        <div className="modal-actions">
          <Button type="button" variant="outline" onClick={testSavedClone} disabled={busy||referenceBusy||voiceDirty||!savedCloneReady}>使用已保存配置测试克隆声音</Button>
          <Button type="submit" disabled={busy||referenceBusy||!referenceSupported}><Check size={15}/>保存克隆声音配置</Button>
        </div>
      </form>}
      {panel==='effects'&&<><h2>沉浸光效</h2><Toggle label="沉浸光效" description="柔光、玻璃与鼠标染色效果；触屏自动使用静态背景，页面后台停止绘制。" checked={effects} onChange={setEffects}/><Toggle label="减少动态效果" description="减少界面动画与鼠标效果，也尊重系统的减少动态偏好。" checked={reduceMotion} onChange={setReduceMotion}/><p className="space-note">此设备的显示偏好自动保存。鼠标效果限制绘制尺寸与帧率，停止移动后休眠。</p><div className="about-app"><h3>关于瞬光伴行</h3><p>这是以《绝区零》叶瞬光为原型的非官方 AI 陪伴 Web 应用。对话由你配置的模型生成，资料检索、天气、搜索、记忆与语音按实际配置使用。AI 回答可能有误，角色素材归原权利方所有。</p><p>聊天、确认记忆与加密配置保存在运行服务的电脑；模型和工具请求按所选服务处理。</p></div></>}
      {panel==='tools'&&tools&&<form onSubmit={e=>{e.preventDefault();void saveFeature('tools');}}><h2>工具服务</h2><Toggle label="天气查询" description="真实天气服务；请在对话中写明城市，缺失或存在歧义时会澄清。" checked={tools.weather_enabled} onChange={weather_enabled=>setTools({weather_enabled})}/><Toggle label="网页搜索" description="查询结果会返回可打开的来源；工具调用过程显示在对话中。" checked={tools.search_enabled} onChange={search_enabled=>setTools({search_enabled})}/><label className="field">搜索服务<select aria-label="搜索服务" value={tools.search_provider} onChange={e=>setTools({search_provider:e.target.value})}><option value="public">公开搜索（无需 Key）</option><option value="bing">Bing RSS（公开网页检索，尽力服务）</option><option value="wikipedia">Wikipedia（公开百科检索）</option><option value="tavily">Tavily（网页搜索，需要密钥）</option></select><span className="field-hint">公开搜索无需 Key，以 DuckDuckGo 为主，Bing RSS 最多一次回退，仍为尽力服务。Wikipedia 只提供百科内容；Tavily 需密钥。</span></label>{tools.search_provider==='tavily'&&<><label className="field">搜索 API 密钥<Input aria-label="搜索 API 密钥" type="password" autoComplete="off" spellCheck={false} value={toolKey} disabled={clearToolKey||busy} onChange={e=>setToolKey(e.target.value)} placeholder={tools.has_api_key?'已保存；留空保留，填写替换':'填写 Tavily API Key（通常以 tvly- 开头）'}/></label>{tools.has_api_key&&<button className="clear-key" type="button" onClick={()=>{setClearToolKey(v=>!v);setToolKey('');}}>{clearToolKey?'取消移除搜索密钥':'明确移除搜索密钥'}</button>}</>}<label className="field">工具超时（秒）<Input type="number" min={3} max={30} value={tools.timeout??12} onChange={e=>setTools({timeout:Number(e.target.value)})}/></label><p className="space-note">开启工具后，模型可在有限调用次数内选择并执行。失败原因会显示，未返回结果时不会冒充调用成功。</p><Button type="submit" disabled={busy}><Check size={15}/>保存工具配置</Button><div className="reference-panel"><h3>测试已保存的搜索服务</h3><label className="field">测试关键词<Input aria-label="搜索测试关键词" value={toolTestQuery} onChange={e=>setToolTestQuery(e.target.value)} maxLength={200}/></label><Button type="button" variant="outline" disabled={busy||!toolTestQuery.trim()} onClick={()=>void testSearch()}>用已保存配置测试搜索</Button><p className="space-note">一次查询最多返回 3 条来源，使用已保存的配置。Tavily 密钥通常以 tvly- 开头，请勿填写模型服务的密钥。认证失败需检查 Tavily 控制台的密钥有效性与账户权限。</p>{toolTestResult&&<ToolFeedback tools={[{id:'settings-search-test',name:'web_search',status:toolTestResult.ok?'complete':'error',result:toolTestResult}]}/>}</div></form>}
      {panel==='memory'&&<><h2>长期记忆</h2><p className="space-note">本阶段采用手动总结与确认，不自动保存个人资料。</p><MemorySpace compact conversations={conversations} active={active} onChanged={onMemoryChanged}/></>}
      {panel==='reminders'&&reminders&&<form onSubmit={e=>{e.preventDefault();void saveFeature('reminders');}}><h2>关怀提醒</h2><Toggle label="开启休息提醒" checked={reminders.enabled} onChange={enabled=>setReminder({enabled})}/><label className="field">间隔（分钟）<Input type="number" required min={1} max={480} value={reminders.interval_minutes} onChange={e=>setReminder({interval_minutes:Number(e.target.value)})}/></label><div className="field-row"><label className="field">安静时段开始<Input type="time" value={reminders.quiet_start} onChange={e=>setReminder({quiet_start:e.target.value})}/></label><label className="field">安静时段结束<Input type="time" value={reminders.quiet_end} onChange={e=>setReminder({quiet_end:e.target.value})}/></label></div><label className="field">时区<Input value={reminders.timezone} onChange={e=>setReminder({timezone:e.target.value})}/></label><Toggle label="语音提醒" description="需要已启用并配置 TTS；播放可能受浏览器后台限制。" checked={reminders.voice} onChange={voice=>setReminder({voice})}/><div className="inline-actions"><Button type="button" variant="outline" onClick={()=>setReminder({paused_until:reminders.paused_until?null:new Date(Date.now()+3600000).toISOString()})}>{reminders.paused_until?'恢复提醒':'暂停一小时（保存生效）'}</Button><Button type="button" variant="outline" onClick={onTestReminder}><Play size={15}/>立即测试</Button></div>{reminders.paused_until&&<p className="space-note">暂停到 {new Date(reminders.paused_until).toLocaleString('zh-CN')}</p>}<p className="space-note">按时间间隔触发，不检测坐姿。页面需打开并连接服务；后台可能延迟，浏览器关闭后不能保证提醒。重连不补发积压提醒。</p><Button type="submit" disabled={busy}><Check size={15}/>保存提醒配置</Button></form>}
      {(!featureDraft&&panel!=='model'&&panel!=='effects'&&panel!=='memory')&&<p>服务配置暂未读取，请关闭后重试。</p>}{busy&&<div className="settings-progress" role="status"><LoaderCircle className="spin" size={16}/>请求处理中…</div>}{notice&&<div className="settings-notice" role="status">{notice}</div>}
    </section></div></DialogContent></Dialog>;
}
function SearchIcon(){return <ArrowUpRight size={15}/>;}
