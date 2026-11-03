"""Read-only checks of final encoded files; write independent QA evidence here."""
from pathlib import Path
import json,hashlib,sys
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
import generate_idle as idle
HERE=Path(__file__).resolve().parent

def run():
    qa=HERE/'qa';qa.mkdir(exist_ok=True)
    source=Image.open(idle.SOURCE).convert('RGBA')
    interior=np.asarray(source.getchannel('A').filter(ImageFilter.MinFilter(7)))==255
    report={'date':'2026-11-02','method':'Pillow decode of final delivered bytes, not stale render buffers','artifacts':{},'protected_files_unchanged':True}
    for path,digest in json.loads((HERE/'protected-before.json').read_text()).items():
        assert idle.sha256(Path(path))==digest,path
    for ext in ('webp','gif'):
        file=HERE/('portrait-idle.'+ext)
        im=Image.open(file); frames=[];dur=[];partial=[];holes=[];hashes=[]
        for i in range(im.n_frames):
            im.seek(i);im.load();rgba=idle.canonical(im.convert('RGBA'));a=np.array(rgba)
            frames.append(a);dur.append(im.info['duration'])
            partial.append(int(((a[...,3]>0)&(a[...,3]<255)).sum()))
            holes.append(int((a[...,3][interior]<255).sum()))
            hashes.append(hashlib.sha256(rgba.tobytes()).hexdigest())
        foot_delta=max(int(np.abs(a[660:].astype(int)-frames[0][660:].astype(int)).max()) for a in frames)
        assert foot_delta==0
        assert len(frames)==120 and dur==[50]*120 and im.info['loop']==0
        if ext=='webp':
            assert max(holes)==0 and min(partial)>0
            src=np.array(idle.canonical(source)); borders=np.concatenate([src[:,0],src[:,-1],src[0],src[-1]])
            for a in frames:
                other=np.concatenate([a[:,0],a[:,-1],a[0],a[-1]])
                assert np.array_equal(borders,other)
        sheet=Image.new('RGB',(4*360,2*220),'#e5eaf0');draw=ImageDraw.Draw(sheet)
        for j,i in enumerate(range(31,39)):
            rgba=Image.fromarray(frames[i]);face=idle.on_bg(rgba,idle.BG).crop((192,103,309,165)).resize((351,186),Image.Resampling.LANCZOS)
            x=(j%4)*360;y=(j//4)*220;sheet.paste(face,(x+4,y+30))
            draw.text((x+7,y+5),f'{ext.upper()} f{i:03d} | {i/20:.2f}s | lid {idle.blink_at(i/20):.2f}',font=idle.font(16),fill='#263449')
        sheet.save(qa/(ext+'-all-blink-frames.png'))
        Image.fromarray(frames[33]).save(HERE/('portrait-idle-'+ext+'-closed.png'))
        report['artifacts'][ext]={'sha256':idle.sha256(file),'frames':len(frames),'duration_ms':sum(dur),'foot_max_change':foot_delta,'interior_transparency_holes_max':max(holes),'partial_alpha_pixels_min':min(partial),'partial_alpha_pixels_max':max(partial),'frame_sha256':hashes}
    # Full-scale comparison uses current original framing, not reference head pixels.
    face=Image.open(HERE/'keyframes/closed.png').convert('RGBA')
    idle.on_bg(face,idle.BG).crop((192,103,309,165)).resize((702,372),Image.Resampling.LANCZOS).save(HERE/'closed-eyes-preview.png')
    (qa/'decoded-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk!='frame_sha256'} for k,v in report['artifacts'].items()},indent=2))

if __name__=='__main__':run()
