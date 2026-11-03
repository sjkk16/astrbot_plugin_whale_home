"""Local, deterministic portrait idle preview. Requires Pillow >= 10 and NumPy.

Run: python generate_idle.py
No network, AI API, SDK, project-manifest edits, or source-asset writes.
The eye artwork stays at its original coordinates: an animated lid OCCLUDES
it. The source iris is never scaled. Head and feet remain stationary;
nearby hair follows the continuous upper-body field, not a separate hair swing.
Closed lashes are extracted from the user-selected inspection-pet-eyes.png.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
from prepare_reference_lashes import LASHES, extract as extract_reference_lashes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / 'views/home/art/portrait.webp'
STUDY = ROOT / 'art-sources/portrait-animation/source-check.json'
SOURCE_SHA256 = '32017a191e1893f99a4f1590b2cec1068e52d7d34d9210d142c83aad0009b046'
FPS = 20
SECONDS = 6
FRAMES = FPS * SECONDS
BG = '#eef2f7'
SCALE = 4
FACE_BOX = (197, 110, 304, 153)
# Measured on the 500x991 original; left/right are viewer coordinates.
EYES = [
    dict(name='left',
         erase=[(207,130),(211,127),(216,123),(219,122),(220,120.7),
                (224,122),(228,122.8),(233,124),(237,125),(241,127.5),
                (240.5,130),(242.5,131.7),(243.3,135),(241.5,139),
                (237,142),(231,144.2),(223,145),(215,143),(210,140),(207,138)],
         upper=[(208.5,135),(217,122),(231,120),(242,132)],
         closed=LASHES[0]['closed'],
         lower=[(208.5,135),(217,147),(231,147),(242,135)],
         outer=0, skin_box=(205,114,246,152)),
    dict(name='right',
         erase=[(258,128.5),(261,125),(264,122),(268,120),(275,119),
                (279.5,117.5),(282.5,119.5),(285.5,120),(287.8,118.6),
                (289.4,121.8),(292,123.3),(293.7,125.6),(297.6,128.5),
                (297,131.4),(294.5,134),(292,138),(286,140.5),
                (278,141.2),(269,140.5),(264,138.3),(261,134),(260,131)],
         upper=[(260,129),(268,116.5),(285,116.5),(296,130)],
         closed=LASHES[1]['closed'],
         lower=[(260,129),(265,144.5),(288,144.5),(296,130)],
         outer=1, skin_box=(252,110,300,149)),
]


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x*x*(3.0-2.0*x)


def blink_at(t):
    """Two 350ms blinks: close 100ms, hold 50ms, reopen 200ms."""
    for start in (1.55, 4.55):
        dt = t-start
        if 0 <= dt < .10:
            return float(smoothstep(dt/.10))
        if .10 <= dt < .15:
            return 1.0
        if .15 <= dt < .35:
            return float(1.0-smoothstep((dt-.15)/.20))
    return 0.0


def breath_at(t):
    return .5-.5*math.cos(2*math.pi*t/3.0)


def bezier(points, count=101):
    p = np.asarray(points, dtype=float)
    t = np.linspace(0, 1, count)[:, None]
    return (1-t)**3*p[0]+3*(1-t)**2*t*p[1]+3*(1-t)*t*t*p[2]+t**3*p[3]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def font(size):
    path = Path('C:/Windows/Fonts/arial.ttf')
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


class Animator:
    def __init__(self):
        if sha256(SOURCE) != SOURCE_SHA256:
            raise ValueError('Source differs from the inspected original; remeasure before rendering.')
        self.original = Image.open(SOURCE).convert('RGBA')
        assert self.original.size == (500, 991)
        study = json.loads(STUDY.read_text(encoding='utf-8'))
        assert study['source_sha256'] == SOURCE_SHA256
        # Study is used for its measurements/provenance, NOT its pinched-eye frame.
        self.face = self.original.crop(FACE_BOX).resize(
            ((FACE_BOX[2]-FACE_BOX[0])*SCALE,(FACE_BOX[3]-FACE_BOX[1])*SCALE),
            Image.Resampling.LANCZOS)
        extract_reference_lashes()
        self.eye_data = [self.prepare_eye(e) for e in EYES]
        self.reference_lashes = [np.array(Image.open(HERE/'assets'/(e['name']+'-reference-lash.png')).convert('RGBA')) for e in EYES]
        self.blink_cache = {}

    def pt(self, xy):
        return ((float(xy[0])-FACE_BOX[0])*SCALE, (float(xy[1])-FACE_BOX[1])*SCALE)

    def prepare_eye(self, eye):
        mask = Image.new('L', self.face.size)
        ImageDraw.Draw(mask).polygon([self.pt(p) for p in eye['erase']], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(.34*SCALE))
        # Fit a smooth 2D skin-color field to NEARBY SKIN, not the old study's
        # horizontal color bands. Exclude eyes, lashes, hair, and white sclera.
        native_mask = Image.new('L', self.original.size)
        ImageDraw.Draw(native_mask).polygon(eye['erase'], fill=255)
        exclusion = np.array(native_mask.filter(ImageFilter.MaxFilter(7))) > 0
        rgb = np.array(self.original)[...,:3].astype(float)
        yy,xx = np.mgrid[:991,:500]
        x0,y0,x1,y1 = eye['skin_box']
        select = ((xx>=x0)&(xx<x1)&(yy>=y0)&(yy<y1)&~exclusion &
                  (rgb[...,0]>224)&(rgb[...,1]>157)&(rgb[...,2]>145)&
                  (rgb[...,0]-rgb[...,1]>9)&(rgb[...,0]-rgb[...,2]>12)&
                  (rgb[...,1]-rgb[...,2]<33))
        cx,cy = np.mean(np.asarray(eye['erase']),axis=0)
        xn=(xx-cx)/25; yn=(yy-cy)/25
        A=np.stack([np.ones_like(xx),xn,yn,xn*yn,xn*xn,yn*yn],axis=-1)
        coeff=np.linalg.lstsq(A[select],rgb[select],rcond=None)[0]
        Y,X=np.mgrid[:self.face.height,:self.face.width]
        X=(FACE_BOX[0]+(X+.5)/SCALE-.5-cx)/25
        Y=(FACE_BOX[1]+(Y+.5)/SCALE-.5-cy)/25
        B=np.stack([np.ones_like(X),X,Y,X*Y,X*X,Y*Y],axis=-1)
        colors=np.clip(B@coeff,0,255).astype(np.uint8)
        patch=Image.fromarray(colors).convert('RGBA')
        return dict(mask=mask,patch=patch,skin_samples=int(select.sum()))

    def blink(self, closure):
        if closure < 1e-7:
            return self.original.copy()
        key=round(closure,6)
        if key in self.blink_cache:
            return self.blink_cache[key].copy()
        face=self.face.copy()
        for eye_index,(eye,data) in enumerate(zip(EYES,self.eye_data)):
            # Remove the original iris/lash region using an antialiased skin mask.
            face=Image.composite(data['patch'],face,data['mask'])
            top=np.asarray(eye['upper'])*(1-closure)+np.asarray(eye['closed'])*closure
            # Lower lid rises gently rather than squeezing the image.
            low=np.asarray(eye['lower'])*(1-closure)+np.asarray(eye['closed'])*closure
            upper=bezier(top); lower=bezier(low)
            opening=Image.new('L',face.size)
            if closure < .998:
                poly=[self.pt(p) for p in upper]+[self.pt(p) for p in lower[::-1]]
                ImageDraw.Draw(opening).polygon(poly,fill=255)
                # The reveal mask is clipped to the measured eye region.
                opening=Image.fromarray(np.minimum(np.array(opening),np.array(data['mask'])))
                face=Image.composite(self.face,face,opening)
            # Warp only the extracted eyelash ink along the moving lid curve.
            # This keeps the reference's thicker smiling closed-eye brush shape,
            # while revealing/occluding the unscaled original iris underneath.
            ink=self.lash_on_curve(eye_index, upper, closure)
            face=Image.alpha_composite(face,ink)
        out=self.original.copy()
        native_size=(FACE_BOX[2]-FACE_BOX[0],FACE_BOX[3]-FACE_BOX[1])
        changed=np.any(np.array(face)!=np.array(self.face),axis=-1).astype(np.uint8)*255
        coverage=Image.fromarray(changed).filter(ImageFilter.MaxFilter(5)).resize(native_size,Image.Resampling.BOX)
        native=Image.composite(face.resize(native_size,Image.Resampling.LANCZOS),
                               self.original.crop(FACE_BOX),coverage)
        out.paste(native,FACE_BOX[:2])
        self.blink_cache[key]=out.copy()
        return out

    def lash_on_curve(self, eye_index, upper, closure):
        eye=EYES[eye_index]; ref=LASHES[eye_index]
        rgba=self.reference_lashes[eye_index].astype(np.float32)
        baseline=bezier(ref['baseline'],301)
        source_span=baseline[-1,0]-baseline[0,0]
        dest_span=upper[-1,0]-upper[0,0]
        Y,X=np.mgrid[:self.face.height,:self.face.width].astype(np.float32)
        gx=FACE_BOX[0]+(X+.5)/SCALE-.5
        gy=FACE_BOX[1]+(Y+.5)/SCALE-.5
        u=(gx-upper[0,0])/dest_span
        ref_x=baseline[0,0]+u*source_span
        ref_y=np.interp(ref_x,baseline[:,0],baseline[:,1])
        dst_y=np.interp(gx,upper[:,0],upper[:,1])
        # Thicker lash builds continuously during the closing phase. Never
        # compress the eyeball or transplant the reference's surrounding skin.
        thickness=.55+.45*float(smoothstep(closure))
        sy=ref_y+(gy-dst_y)/(dest_span/source_span*thickness)-ref['box'][1]
        sx=ref_x-ref['box'][0]
        valid=(sx>=0)&(sy>=0)&(sx<rgba.shape[1]-1)&(sy<rgba.shape[0]-1)
        sx=np.clip(sx,0,rgba.shape[1]-1.001);sy=np.clip(sy,0,rgba.shape[0]-1.001)
        x0=np.floor(sx).astype(int);y0=np.floor(sy).astype(int)
        wx=(sx-x0)[...,None];wy=(sy-y0)[...,None]
        sample=(rgba[y0,x0]*(1-wx)*(1-wy)+rgba[y0,x0+1]*wx*(1-wy)+
                rgba[y0+1,x0]*(1-wx)*wy+rgba[y0+1,x0+1]*wx*wy)
        sample[...,3]*=valid
        return Image.fromarray(np.clip(np.rint(sample),0,255).astype(np.uint8))

    @staticmethod
    def warp(image, amount):
        if amount < 1e-9:
            return image.copy()
        # Float32 premultiplied-alpha inverse mapping, rounded to nearest. Pillow's
        # integer mesh sampler floors almost-static subpixel colors, causing a
        # brightness step at the loop seam; this avoids that quantization jump.
        source=np.array(image)
        yy,xx=np.mgrid[180:660,0:500].astype(np.float32)
        strength=(smoothstep((yy-184)/95)*(1-smoothstep((yy-390)/245)) *
                  np.exp(-((xx-250)/174)**6) *
                  smoothstep(xx/20)*smoothstep((499-xx)/20))
        sx=np.clip(xx-amount*strength*(xx-250)*.006,0,499)
        sy=yy+amount*strength*1.6
        x0=np.floor(sx).astype(np.int32);y0=np.floor(sy).astype(np.int32)
        x1=np.minimum(x0+1,499);y1=np.minimum(y0+1,990)
        wx=(sx-x0)[...,None];wy=(sy-y0)[...,None]
        premul=source.astype(np.float32)
        premul[...,:3]*=premul[...,3:]/255.0
        rgba=(premul[y0,x0]*(1-wx)*(1-wy)+premul[y0,x1]*wx*(1-wy)+
              premul[y1,x0]*(1-wx)*wy+premul[y1,x1]*wx*wy)
        rgba[...,:3]=np.divide(rgba[...,:3]*255,rgba[...,3:],
                               out=np.zeros_like(rgba[...,:3]),where=rgba[...,3:]>0)
        result=source.copy()
        result[180:660]=np.clip(np.rint(rgba),0,255).astype(np.uint8)
        # Never change canvas-edge pixels, including invisible source RGB.
        result[:, :2]=source[:, :2];result[:, -2:]=source[:, -2:]
        return Image.fromarray(result)

    def frame(self,t):
        return self.warp(self.blink(blink_at(t)),breath_at(t))


def canonical(im):
    # Invisible RGB in the original WebP contains unrelated encoder colors.
    # Clear only alpha==0; this changes no visible pixels and helps delta coding.
    a=np.array(im);a[a[...,3]==0,:3]=0
    return Image.fromarray(a)


def visible_pixels(a):
    alpha=a[...,3:]/255.0
    return a[...,:3]*alpha+238*(1-alpha)


def on_bg(im,color):
    bg=Image.new('RGBA',im.size,color);bg.alpha_composite(im)
    return bg.convert('RGB')


def contact_sheet(anim,out):
    keys=[(name,blink_at(i/FPS),breath_at(i/FPS)) for name,i in
          [('open',0),('half-closed',32),('closed',33),('half-open',36),('inhale',30),('exhale',60)]]
    directory=out/'keyframes'; directory.mkdir(exist_ok=True)
    sheet=Image.new('RGB',(6*300,805),'#e5eaf0');d=ImageDraw.Draw(sheet)
    face_sheet=Image.new('RGB',(6*360,330),'#e5eaf0'); fd=ImageDraw.Draw(face_sheet)
    for i,(label,c,b) in enumerate(keys):
        im=anim.warp(anim.blink(c),b); im.save(directory/(label+'.png'))
        full=on_bg(im,BG).resize((300,595),Image.Resampling.LANCZOS)
        sheet.paste(full,(i*300,35))
        face=on_bg(im,BG).crop((192,104,308,164)).resize((300,155),Image.Resampling.LANCZOS)
        sheet.paste(face,(i*300,645))
        d.text((i*300+10,8),label,fill='#263449',font=font(18))
        crop=on_bg(im,BG).crop((197,109,304,153)).resize((350,144),Image.Resampling.LANCZOS)
        face_sheet.paste(crop,(i*360+5,42)); fd.text((i*360+8,10),label,fill='#263449',font=font(20))
        pix=on_bg(im,BG).crop((197,109,304,153)).resize((350,144),Image.Resampling.NEAREST)
        face_sheet.paste(pix,(i*360+5,185))
    sheet.save(out/'contact-sheet.png');face_sheet.save(out/'face-contact-sheet.png')
    alpha=Image.new('RGB',(1000,1027));ad=ImageDraw.Draw(alpha)
    for i,color in enumerate(('#eef2f7','#172235')):
        alpha.paste(on_bg(anim.warp(anim.blink(1),1),color),(i*500,36))
        ad.rectangle((i*500,0,i*500+499,35),fill=color)
        ad.text((i*500+12,8),'Alpha check / '+('light' if i==0 else 'dark'),fill=('#263449' if i==0 else '#eef2f7'),font=font(18))
    alpha.save(out/'alpha-check.png')


def save_gif(frames,path):
    # One shared palette prevents per-frame palette pumping. Reserve most colors
    # for the portrait while retaining a stable exact background.
    samples=[on_bg(frames[i],BG) for i in (0,31,32,33,34,35,36,37,60,92,94,119)]
    atlas=Image.new('RGB',(500*4,991*3))
    for i,im in enumerate(samples): atlas.paste(im,((i%4)*500,(i//4)*991))
    # Reserve dedicated face colors so the small face does not inherit a
    # clothing-dominated palette with large pink posterization bands.
    face_atlas=Image.new('RGB',(120*len(samples),70))
    for i,im in enumerate(samples):
        face_atlas.paste(im.crop((192,108,312,178)),(i*120,0))
    colors=atlas.quantize(colors=160,method=Image.Quantize.MEDIANCUT).getpalette()[:160*3]
    colors+=face_atlas.quantize(colors=95,method=Image.Quantize.MEDIANCUT).getpalette()[:95*3]
    colors+=[238,242,247]  # Light-background candidate; Pillow palette lookup may quantize nearby RGB.
    palette=Image.new('P',(1,1));palette.putpalette(colors)
    indexed=[on_bg(im,BG).quantize(palette=palette,dither=Image.Dither.NONE) for im in frames]
    indexed[0].save(path,save_all=True,append_images=indexed[1:],duration=50,loop=0,optimize=False,disposal=1)


def verify(anim,frames,out):
    original=np.array(canonical(anim.original))
    # Breathing must not move the face, hair top or feet. Eye changes are tested
    # separately. Source pixels below y=660 remain byte-for-byte stationary.
    foot_max=max(int(np.abs(np.array(im)[660:].astype(int)-original[660:].astype(int)).max()) for im in frames)
    head_max=max(int(np.abs(np.array(im)[:100].astype(int)-original[:100].astype(int)).max()) for im in frames)
    assert foot_max==0 and head_max==0
    loop0=np.array(anim.frame(0));loop6=np.array(anim.frame(6))
    assert np.array_equal(loop0,loop6)
    assert all(im.size==(500,991) for im in frames)
    protected=[SOURCE,STUDY,ROOT/'views/home/art/character-motion/manifest.json',ROOT/'frontend/preview-assets/art/character-motion/manifest.json']
    report=dict(source=str(SOURCE),source_sha256=sha256(SOURCE),
                render=dict(size=[500,991],fps=FPS,duration_ms=6000,frames=120,blink_count=2,
                            blink_starts_seconds=[1.55,4.55],breathing_period_seconds=3,closed_eye_style='user-reference-thick-smiling-lashes',
                            closed_eye_reference_sha256=sha256(HERE/'inspection-pet-eyes.png')),
                checks=dict(feet_max_pixel_change=foot_max,head_top_max_pixel_change=head_max,
                            exact_loop_endpoint_match=True,eye_iris_resampling=False),
                protected_files={str(p.relative_to(ROOT)):sha256(p) for p in protected if p.exists()},
                artifacts={})
    for name in ('portrait-idle.webp','portrait-idle.gif'):
        p=out/name; durations=[];decoded=[]
        with Image.open(p) as im:
            info=im.info.copy()
            assert im.is_animated and im.size==(500,991)
            for n in range(im.n_frames):
                im.seek(n); im.load(); durations.append(im.info.get('duration',0))
                decoded.append(np.array(im.convert('RGBA')))
            count=im.n_frames
        assert sum(durations)==6000,(name,durations)
        assert info.get('loop')==0
        assert all(d==50 for d in durations),(name,'duration not 50ms')
        assert count==120,(name,count)
        seam=float(np.abs(visible_pixels(decoded[-1])-visible_pixels(decoded[0])).mean())
        step=[float(np.abs(visible_pixels(a)-visible_pixels(b)).mean()) for a,b in zip(decoded,decoded[1:])]
        assert seam<max(step)*.2,(name,'large loop seam')
        if name.endswith('.webp'):
            # Lossless WebP preserves premultiplied-rendered visible RGBA.
            for expected,got in zip(frames,decoded):
                expected=np.array(expected);visible=expected[...,3]>0
                assert np.array_equal(expected[visible],got[visible])
            assert any(np.any((a[...,3]>0)&(a[...,3]<255)) for a in decoded[:1])
        report['artifacts'][name]=dict(bytes=p.stat().st_size,sha256=sha256(p),
            decoded_frames=count,duration_ms=sum(durations),frame_durations_ms=sorted(set(durations)),
            loop=info.get('loop'),seam_mean_absolute_change=round(seam,6),max_step_change=round(max(step),6))
    assert sha256(SOURCE)==SOURCE_SHA256
    (out/'verification.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return report


def write_preview(out):
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>立绘待机 · 动图样片</title><style>
*{box-sizing:border-box}body{margin:0;background:#edf1f6;color:#24324a;font-family:system-ui,"Microsoft YaHei",sans-serif}main{max-width:1140px;margin:auto;padding:24px}h1{font-size:25px;margin:0 0 8px}p{color:#64748b;font-size:14px}.controls{display:flex;gap:8px;margin:18px 0}button{padding:8px 16px;border:1px solid #ccd5e0;border-radius:8px;background:white;color:#24324a;cursor:pointer}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.card{background:white;border:1px solid #dce4ee;border-radius:14px;overflow:hidden}.caption{display:flex;justify-content:space-between;padding:14px 18px;font-size:14px}.stage{display:flex;align-items:center;justify-content:center;height:650px;background:#eef2f7}.stage img{height:100%;width:auto;max-width:100%;object-fit:contain}.dark{background:#172235}.checker{background:conic-gradient(#dce2eb 25%,#f5f7fa 0 50%,#dce2eb 0 75%,#f5f7fa 0) 0 0/24px 24px}a{color:#4464a8}footer{font-size:12px;color:#718096;margin-top:16px}@media(max-width:700px){.grid{grid-template-columns:1fr}.stage{height:570px}}</style>
<main><h1>正常比例立绘 · 待机样片</h1><p>6 秒无缝循环 · 20 fps · 参考图式厚睫毛闭眼 + 肩部轻微呼吸 · 独立预览，未替换项目素材</p>
<div class="controls"><button onclick="setBg('')">浅色背景</button><button onclick="setBg('dark')">深色背景</button><button onclick="setBg('checker')">透明棋盘</button><button onclick="restart()">重新播放</button></div>
<div class="grid"><section class="card"><div class="caption"><b>透明动态 WebP</b><a href="portrait-idle.webp" download>下载 WebP</a></div><div id="webp-stage" class="stage"><img id="webp" src="portrait-idle.webp" alt="透明背景立绘待机动图"></div></section><section class="card"><div class="caption"><b>浅色背景 GIF</b><a href="portrait-idle.gif" download>下载 GIF</a></div><div class="stage"><img id="gif" src="portrait-idle.gif" alt="浅色背景立绘待机动图"></div></section></div>
<footer>本地原图处理，无生成式 AI、无外部服务。仅个人预览；不代表 Live2D 模型或项目正式审核完成。<br><a href="contact-sheet.png">关键帧</a> · <a href="alpha-check.png">透明边缘检查</a> · <a href="verification.json">验证记录</a></footer>
<script>function setBg(c){document.getElementById('webp-stage').className='stage '+c}function restart(){for(const id of ['webp','gif']){const img=document.getElementById(id);img.src=id==='webp'?'portrait-idle.webp?r='+Date.now():'portrait-idle.gif?r='+Date.now()}}</script></main></html>'''
    (out/'preview.html').write_text(html,encoding='utf-8')
    (out/'README.md').write_text('''# Portrait idle v1 / 正常比例立绘待机样片

- `portrait-idle.webp`: 500 × 991，6 秒，120 帧，20 fps，透明背景，无限循环，无损编码。
- `portrait-idle.gif`: 同一段动画，浅色底 `#eef2f7`，共享 256 色调色板（160 全局色 + 95 面部色 + 1 背景候选色）；GIF 色彩少于 WebP。
- `preview.html`: 本地并排预览，可切换 WebP 背景。
- `keyframes/`: 原尺寸 RGBA 关键帧。`contact-sheet.png`、`face-contact-sheet.png`、`alpha-check.png` 为静态检查图。
- `verification.json`: 帧数、时长、循环、固定脚点、透明通道与源文件摘要检查。
- 复现：安装 Pillow >= 10 与 NumPy 后，执行 `python generate_idle.py`（需保留同目录 `prepare_reference_lashes.py` 及参考图）；`--preview-only` 只导出关键帧检查图。

## 动效实现
原画眼睛保持位置及大小，以移动的上眼睑遮挡原瞳孔，少量下眼睑抬升，闭眼从用户指定 `inspection-pet-eyes.png` 中仅提取深色睫毛笔触，映射至原眼位；不复制参考脸部皮肤或改变原脸型。闭眼区域颜色由周围皮肤二维拟合并抗锯齿融合，不复用旧分层试验稿的压扁眼睛。呼吸为肩部/躯干连续局部变形，最大纵向位移 1.6px；头、脚固定，邻近发丝只随连续局部场微动，不独立甩发。所有处理均在本地执行，无绘图 API 或生成模型。

## 来源与边界
原图：项目 `views/home/art/portrait.webp`；测量参考：既有 `art-sources/portrait-animation/source-check.json`。保留原图许可边界，仅个人预览，不推定公开分发授权。未覆盖原图、未改项目清单/审核标记、仅为透明动图。不包含转头、张嘴或甩发动作。
''',encoding='utf-8')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--preview-only',action='store_true')
    args=parser.parse_args(); HERE.mkdir(exist_ok=True)
    assert features.check('webp')
    protected=[SOURCE,STUDY,ROOT/'views/home/art/character-motion/manifest.json',ROOT/'frontend/preview-assets/art/character-motion/manifest.json']
    protected_before={p:sha256(p) for p in protected if p.exists()}
    anim=Animator();contact_sheet(anim,HERE)
    print('Skin fit samples:',[e['skin_samples'] for e in anim.eye_data],flush=True)
    if args.preview_only:return
    frames=[]
    for i in range(FRAMES):
        frames.append(canonical(anim.frame(i/FPS)))
        if i%20==0:print(f'Render {i}/{FRAMES}',flush=True)
    frames[0].save(HERE/'portrait-idle.webp',save_all=True,append_images=frames[1:],duration=50,
                   loop=0,lossless=True,quality=80,method=4,exact=False,minimize_size=False,
                   kmin=9,kmax=17,allow_mixed=False)
    print('WebP encoded',flush=True);save_gif(frames,HERE/'portrait-idle.gif')
    print('GIF encoded',flush=True);report=verify(anim,frames,HERE);write_preview(HERE)
    assert all(sha256(p)==digest for p,digest in protected_before.items())
    report['checks']['source_and_manifests_unchanged']=True
    (HERE/'verification.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(report['artifacts'],indent=2),flush=True)


if __name__=='__main__': main()

