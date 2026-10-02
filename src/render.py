#!/usr/bin/env python3
"""STAK box reveal renderer.

Usage examples
  python3 src/render.py --size 1200 --bg transparent --formats apng,webm,png
  python3 src/render.py --size 1400 --bg "#0A1020" --mode once --formats gif,mp4
  python3 src/render.py --size 1200 --bg "#0A1020" --mode loop --formats gif

Plates in ./plates are exact Figma renders over black and over white (true alpha is
solved from the pair). Masters are 2400px tall; every size is a downscale.
Motion: beam lights first (soft bloom), then each coin fades in behind the box's
front faces, clears their top edge into the mouth, and floats up into the beam.
Order and tempo follow the STAK hero (Jitter): opacity linear, rise on
cubic-bezier(0,0,0,1): NVIDIA 0.00s · Apple 1.25s · Shopify 1.67s · Amazon 2.09s ·
Twitch 2.63s · Google 3.27s (1.9 s first, 2.5 s each after).
"""
import argparse, os, sys, math, shutil, subprocess, zipfile
import numpy as np, cv2
from PIL import Image
from scipy.ndimage import gaussian_filter

HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE); PL=os.path.join(ROOT,'plates')
TILE_W,TILE_H=653.0,580.0                  # the Figma tile, unscaled (node 634:9020 in DE-STAK)
# coin image bounds in unscaled tile coordinates
COINS={'google':(302.80,153.23,146.00,146.00),'amazon':(349.17,262.49,60.91,60.91),'shopify':(302.94,241.37,61.10,61.10),
       'twitch':(292.12,96.27,87.40,87.40),'nvidia':(226.21,168.47,106.55,106.55),'apple':(252.49,258.70,67.77,67.77)}
SEQ=[('nvidia',0.00,1.9),('apple',1.25,2.5),('shopify',1.67,2.5),('amazon',2.09,2.5),('twitch',2.63,2.5),('google',3.27,2.5)]
T_BEAM0,T_BEAM1,T_COIN0,SEQ_LEN,HOLD=0.4,1.6,1.5,5.8,2.0
TOTAL=T_COIN0+SEQ_LEN+HOLD

def clamp01(v): return max(0.0,min(1.0,v))
def seg(T,a,b): return clamp01((T-a)/(b-a))
def eio(t): t=clamp01(t); return 0.5-0.5*math.cos(math.pi*t)
def bez(p1x,p1y,p2x,p2y):
    def f(t):
        t=clamp01(t); lo,hi=0.0,1.0
        for _ in range(28):
            u=(lo+hi)/2; x=3*(1-u)**2*u*p1x+3*(1-u)*u*u*p2x+u**3
            if x<t: lo=u
            else: hi=u
        u=(lo+hi)/2; return 3*(1-u)**2*u*p1y+3*(1-u)*u*u*p2y+u**3
    return f
RISE=bez(0,0,0,1)

def load_pair(name):
    """black/white plate pair -> premultiplied RGB (float) and alpha (float 0..1)"""
    b=np.array(Image.open(f'{PL}/{name}_black.png').convert('RGB')).astype(np.float32)
    w=np.array(Image.open(f'{PL}/{name}_white.png').convert('RGB')).astype(np.float32)
    a=np.clip(1.0-(w-b).mean(axis=2)/255.0,0,1)
    return b,a                               # over black == premultiplied colour

def resize_premult(p,a,scale):
    if abs(scale-1)<1e-6: return p,a
    h,w=a.shape; nw,nh=max(1,int(round(w*scale))),max(1,int(round(h*scale)))
    interp=cv2.INTER_AREA if scale<1 else cv2.INTER_CUBIC
    return cv2.resize(p,(nw,nh),interpolation=interp),cv2.resize(a,(nw,nh),interpolation=interp)

def over(dst_p,dst_a,src_p,src_a):
    """premultiplied 'over' in place"""
    k=(1-src_a)[:,:,None]; dst_p[:]=src_p+dst_p*k; dst_a[:]=src_a+dst_a*(1-src_a)

class Scene:
    def __init__(self,size):
        self.S=size; K=size/TILE_H; self.K=K
        full_w=int(round(TILE_W*K)); self.cx0=(full_w-size)//2
        master_h=2400; s=size/master_h
        def plate(name):
            p,a=load_pair(name); p,a=resize_premult(p,a,s)
            p=p[:size,self.cx0:self.cx0+size]; a=a[:size,self.cx0:self.cx0+size]
            return np.ascontiguousarray(p),np.ascontiguousarray(a)
        self.base_p,self.base_a=plate('base')        # box + beam
        self.box_p,self.box_a=plate('noray')        # box only
        self.face_p,self.face_a=plate('faces')      # front faces (occluder shape)
        # beam light and its bloom (premultiplied additive)
        light=np.clip(self.base_p-self.box_p,0,None); self.light_a=np.clip(self.base_a-self.box_a,0,1)
        sig=max(6,int(28*s*2)); self.bloom=gaussian_filter(light,(sig,sig,0)); self.bloom_a=np.clip(self.bloom.max(axis=2)/255.0,0,1)
        # coins
        self.coins={}
        for key,(x,y,w,h) in COINS.items():
            p,a=load_pair(key); p,a=resize_premult(p,a,s); pad=int(round(2*s))
            p=p[pad:p.shape[0]-pad,pad:p.shape[1]-pad]; a=a[pad:a.shape[0]-pad,pad:a.shape[1]-pad]
            cx=(x+w/2)*K-self.cx0; cy=(y+h/2)*K
            top=self.occ_top(cx); r=w/2*K*0.72
            self.coins[key]={'p':p,'a':a,'cx':cx,'cy':cy,'start':max(cy+70*K/2.07, top+r*1.05+40*K/2.07)}
    def occ_top(self,x):
        col=self.face_a[:,int(max(0,min(self.S-1,x)))]; i=np.where(col>0.5)[0]; return int(i[0]) if len(i) else self.S
    def coin_layer(self,key,cy,alpha):
        c=self.coins[key]; h,w=c['a'].shape; S=self.S
        M=np.float32([[1,0,c['cx']-w/2],[0,1,cy-h/2]])
        p=cv2.warpAffine(c['p'],M,(S,S),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0))
        a=cv2.warpAffine(c['a'],M,(S,S),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
        return p*alpha,a*alpha
    def frame(self,T,bg):
        S=self.S; beam=eio(seg(T,T_BEAM0,T_BEAM1)); Tc=T-T_COIN0
        # canvas
        if bg is None: P=np.zeros((S,S,3),np.float32); A=np.zeros((S,S),np.float32)
        else: P=np.tile(np.array(bg,np.float32),(S,S,1)); A=np.ones((S,S),np.float32)
        # box, then the beam lit to 'beam' (lerp box -> box+beam in premultiplied space), plus bloom
        sp=self.box_p+(self.base_p-self.box_p)*beam; sa=self.box_a+(self.base_a-self.box_a)*beam
        if beam>0:
            g=0.55*math.sin(math.pi*min(1,beam))+0.16*beam
            sp=sp+self.bloom*g; sa=np.clip(sa+self.bloom_a*g*(1-sa),0,1)
        over(P,A,sp,sa)
        # coins behind the front faces; nearer (lower-resting) coins drawn last
        draw=[]
        for key,st,dur in SEQ:
            p=seg(Tc,st,st+dur)
            if p<=0: continue
            c=self.coins[key]; cy=c['start']+(c['cy']-c['start'])*RISE(p); draw.append((c['cy'],key,cy,min(1.0,p/0.4)))
        for _,key,cy,al in sorted(draw):
            cp,ca=self.coin_layer(key,cy,al); over(P,A,cp,ca)
        # the box front, coloured from the lit scene, on top
        fa=self.face_a*sa; fp=sp*(self.face_a[:,:,None]); over(P,A,fp,fa)
        return P,A

def to_rgba8(P,A):
    a=np.clip(A,0,1); rgb=np.where(a[:,:,None]>1e-4,P/np.maximum(a[:,:,None],1e-4),0)   # un-premultiply for PNG
    return np.dstack([np.clip(rgb,0,255),a*255]).astype(np.uint8)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--size',type=int,default=1200); ap.add_argument('--fps',type=int,default=30)
    ap.add_argument('--bg',default='transparent'); ap.add_argument('--mode',choices=['once','loop'],default='once')
    ap.add_argument('--formats',default='apng,webm,png'); ap.add_argument('--out',default=os.path.join(ROOT,'exports'))
    ap.add_argument('--range',default='',help='render only frames a,b (inclusive) and stop; e.g. 0,139'); ap.add_argument('--encode-only',action='store_true',help='skip rendering, encode existing frames')
    a=ap.parse_args(); bg=None if a.bg.lower()=='transparent' else tuple(int(a.bg.lstrip('#')[i:i+2],16) for i in (0,2,4))
    tag=f"{a.size}-{'alpha' if bg is None else a.bg.lstrip('#').lower()}-{a.mode}"
    fr=os.path.join(a.out,f'_frames_{tag}'); os.makedirs(fr,exist_ok=True); os.makedirs(a.out,exist_ok=True)
    N=int(round(TOTAL*a.fps))
    if not a.encode_only:
        sc=Scene(a.size); lo,hi=(0,N-1) if not a.range else tuple(int(v) for v in a.range.split(','))
        for i in range(lo,hi+1):
            P,A=sc.frame(i/a.fps,bg); im=to_rgba8(P,A) if bg is None else np.clip(P,0,255).astype(np.uint8)
            Image.fromarray(im,'RGBA' if bg is None else 'RGB').save(f'{fr}/f{i:04d}.png')
        if a.range and hi<N-1: print('rendered',lo,'..',hi,'of',N); return
    base=os.path.join(a.out,f'stak-box-reveal-{tag}'); fm=set(a.formats.split(','))
    loop_gif='0' if a.mode=='loop' else '-1'; loop_apng='0' if a.mode=='loop' else '1'
    ff=['ffmpeg','-y','-loglevel','error','-framerate',str(a.fps),'-i',f'{fr}/f%04d.png']
    if 'mp4' in fm and bg is not None: subprocess.run(ff+['-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-movflags','+faststart',base+'.mp4'],check=True)
    if 'gif' in fm: subprocess.run(ff+['-vf','fps=20,split[s0][s1];[s0]palettegen=max_colors=256:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle','-loop',loop_gif,base+'.gif'],check=True)
    if 'webm' in fm: subprocess.run(ff+['-c:v','libvpx-vp9','-pix_fmt','yuva420p' if bg is None else 'yuv420p','-b:v','0','-crf','28','-auto-alt-ref','0',base+'.webm'],check=True)
    if 'apng' in fm: subprocess.run(ff+['-vf','fps=20','-c:v','apng','-plays',loop_apng,'-f','apng',base+'.apng'],check=True)
    if 'png' in fm:
        with zipfile.ZipFile(base+'-png-sequence.zip','w',zipfile.ZIP_DEFLATED) as z:
            for f in sorted(os.listdir(fr)): z.write(os.path.join(fr,f),f)
    Image.open(f'{fr}/f{N-1:04d}.png').save(base+'-poster.png')
    shutil.rmtree(fr); print('done:',tag)

if __name__=='__main__': main()
