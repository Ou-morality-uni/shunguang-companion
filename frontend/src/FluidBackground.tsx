import { useEffect, useRef } from 'react';

const vertexSource = `attribute vec2 position; varying vec2 uv; void main(){uv=position*.5+.5;gl_Position=vec4(position,0.,1.);}`;
// Original dye-advection effect, not a full pressure-projected fluid solver.
const advectSource = `precision mediump float; varying vec2 uv; uniform sampler2D dye;
uniform vec2 pointer; uniform vec2 force; uniform float aspect; uniform float time; uniform float delta; uniform float splat;
void main(){vec2 p=(uv-pointer)*vec2(aspect,1.);float influence=exp(-dot(p,p)*85.);
vec2 curl=vec2(cos(uv.y*18.+time*.4)*sin(uv.x*16.+time*.3),-cos(uv.x*16.+time*.3)*sin(uv.y*18.+time*.4));
vec2 velocity=curl*.007+vec2(-p.y,p.x)*influence*.35+force*influence*.028;
vec3 color=texture2D(dye,clamp(uv-velocity*delta,vec2(.001),vec2(.999))).rgb*pow(.967,delta);
vec3 tint=mix(vec3(.83,.22,.38),vec3(.95,.65,.38),.5+.5*sin(time*.8));color+=tint*exp(-dot(p,p)*950.)*splat*.35;
gl_FragColor=vec4(clamp(color,0.,1.),1.);}`;
const displaySource = `precision mediump float;varying vec2 uv;uniform sampler2D dye;
void main(){vec3 color=texture2D(dye,uv).rgb;float a=max(max(color.r,color.g),color.b);gl_FragColor=vec4(color/max(a,.001),a*.52);}`;

export function FluidBackground({enabled}:{enabled:boolean}) {
  const ref=useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas=ref.current;if(!canvas)return;
    const motion=matchMedia('(prefers-reduced-motion: reduce)');
    if(!enabled||motion.matches||matchMedia('(pointer: coarse)').matches){canvas.dataset.renderer='static';return;}
    const gl=canvas.getContext('webgl',{alpha:true,premultipliedAlpha:false,antialias:false,depth:false,stencil:false});
    if(!gl){canvas.dataset.renderer='fallback';return;}
    const programs:WebGLProgram[]=[],shaders:WebGLShader[]=[];
    let frame=0,buffer:WebGLBuffer|null=null;
    type Target={texture:WebGLTexture;framebuffer:WebGLFramebuffer};let targets:Target[]=[];
    const stop=()=>{cancelAnimationFrame(frame);frame=0;gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);};
    const disposeTargets=()=>{targets.forEach(target=>{gl.deleteTexture(target.texture);gl.deleteFramebuffer(target.framebuffer);});targets=[];};
    const cleanup=()=>{stop();disposeTargets();programs.forEach(p=>gl.deleteProgram(p));shaders.forEach(s=>gl.deleteShader(s));if(buffer)gl.deleteBuffer(buffer);};
    try {
      const shader=(source:string,type:number)=>{const result=gl.createShader(type);if(!result)throw Error('shader');shaders.push(result);gl.shaderSource(result,source);gl.compileShader(result);if(!gl.getShaderParameter(result,gl.COMPILE_STATUS))throw Error('compile');return result;};
      const vertex=shader(vertexSource,gl.VERTEX_SHADER);
      const program=(source:string)=>{const result=gl.createProgram();if(!result)throw Error('program');programs.push(result);gl.attachShader(result,vertex);gl.attachShader(result,shader(source,gl.FRAGMENT_SHADER));gl.linkProgram(result);if(!gl.getProgramParameter(result,gl.LINK_STATUS))throw Error('link');return result;};
      const advect=program(advectSource),display=program(displaySource);
      buffer=gl.createBuffer();if(!buffer)throw Error('buffer');gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
      let width=1,height=1,current=0,lastInput=0,previousFrame=0,pointer=[.5,.5],force=[0,0],splat=0;
      const select=(p:WebGLProgram)=>{gl.useProgram(p);const pos=gl.getAttribLocation(p,'position');gl.enableVertexAttribArray(pos);gl.vertexAttribPointer(pos,2,gl.FLOAT,false,0,0);};
      const clearTargets=()=>{targets.forEach(t=>{gl.bindFramebuffer(gl.FRAMEBUFFER,t.framebuffer);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT);});gl.bindFramebuffer(gl.FRAMEBUFFER,null);};
      const resize=()=>{
        stop();disposeTargets();const scale=Math.min(512/innerWidth,512/innerHeight,1);width=Math.max(1,Math.round(innerWidth*scale));height=Math.max(1,Math.round(innerHeight*scale));canvas.width=width;canvas.height=height;
        for(let i=0;i<2;i++){
          const texture=gl.createTexture(),framebuffer=gl.createFramebuffer();if(!texture||!framebuffer){if(texture)gl.deleteTexture(texture);if(framebuffer)gl.deleteFramebuffer(framebuffer);throw Error('target');}
          targets.push({texture,framebuffer});gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,width,height,0,gl.RGBA,gl.UNSIGNED_BYTE,null);gl.bindFramebuffer(gl.FRAMEBUFFER,framebuffer);gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,texture,0);if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE)throw Error('framebuffer');
        }
        clearTargets();current=0;canvas.dataset.renderer='webgl';
      };
      const draw=(now:number)=>{
        if(motion.matches||document.hidden||now-lastInput>2400){stop();clearTargets();return;}
        frame=requestAnimationFrame(draw);if(now-previousFrame<32)return;
        const delta=Math.min((now-previousFrame)/33.3,2);previousFrame=now;select(advect);gl.viewport(0,0,width,height);gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,targets[current].texture);
        gl.uniform1i(gl.getUniformLocation(advect,'dye'),0);gl.uniform2f(gl.getUniformLocation(advect,'pointer'),pointer[0],pointer[1]);gl.uniform2f(gl.getUniformLocation(advect,'force'),force[0],force[1]);gl.uniform1f(gl.getUniformLocation(advect,'aspect'),innerWidth/innerHeight);gl.uniform1f(gl.getUniformLocation(advect,'time'),now/1000);gl.uniform1f(gl.getUniformLocation(advect,'delta'),delta);gl.uniform1f(gl.getUniformLocation(advect,'splat'),splat);
        gl.bindFramebuffer(gl.FRAMEBUFFER,targets[1-current].framebuffer);gl.drawArrays(gl.TRIANGLES,0,6);current=1-current;select(display);gl.bindFramebuffer(gl.FRAMEBUFFER,null);gl.bindTexture(gl.TEXTURE_2D,targets[current].texture);gl.uniform1i(gl.getUniformLocation(display,'dye'),0);gl.drawArrays(gl.TRIANGLES,0,6);splat=0;force=force.map(v=>v*.93);
      };
      const move=(event:PointerEvent)=>{if(event.pointerType!=='mouse'||motion.matches||document.hidden||gl.isContextLost())return;const next=[event.clientX/innerWidth,1-event.clientY/innerHeight];force=[Math.max(-1,Math.min(1,(next[0]-pointer[0])*45)),Math.max(-1,Math.min(1,(next[1]-pointer[1])*45))];pointer=next;splat=1;lastInput=performance.now();if(!frame){previousFrame=lastInput-34;frame=requestAnimationFrame(draw);}};
      const visibility=()=>{if(document.hidden){stop();clearTargets();}};
      const reduce=()=>{stop();clearTargets();canvas.dataset.renderer=motion.matches?'static':'webgl';};
      const lost=(event:Event)=>{event.preventDefault();stop();canvas.dataset.renderer='fallback';};
      const safeResize=()=>{try{resize();}catch{stop();canvas.dataset.renderer='fallback';}};
      resize();window.addEventListener('pointermove',move,{passive:true});window.addEventListener('resize',safeResize);document.addEventListener('visibilitychange',visibility);motion.addEventListener('change',reduce);canvas.addEventListener('webglcontextlost',lost);
      return()=>{window.removeEventListener('pointermove',move);window.removeEventListener('resize',safeResize);document.removeEventListener('visibilitychange',visibility);motion.removeEventListener('change',reduce);canvas.removeEventListener('webglcontextlost',lost);cleanup();};
    }catch{cleanup();canvas.dataset.renderer='fallback';}
  },[enabled]);
  return <canvas ref={ref} className="pointer-trail" aria-hidden="true" data-effect="fluid" />;
}
