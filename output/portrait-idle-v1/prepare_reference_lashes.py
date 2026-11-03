"""Extract ONLY lash ink from the user-selected local close-eye reference.
No skin/hair/eyebrow region is pasted onto the original face. Pure local processing.
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
HERE=Path(__file__).resolve().parent
REFERENCE=HERE/'inspection-pet-eyes.png'
# Reference-image pixel coordinates. Polygons exclude hair and separate eyebrows.
LASHES=[dict(name='left',box=[66,190,391,317],
 polygon=[(72,274),(90,256),(87,217),(112,222),(143,236),(190,220),(246,205),(285,193),(331,191),(366,193),(376,213),(389,231),(378,245),(154,309),(99,316),(78,305)],
 baseline=[[80,284],[169,245],[299,204],[378,225]],
 closed=[[208.5,137.0],[218.5,131.9],[234,130.0],[242,132.5]]),
 dict(name='right',box=[733,78,1064,182],
 polygon=[(741,132),(765,112),(808,100),(839,99),(892,96),(943,93),(989,99),(1010,86),(1035,78),(1041,88),(1025,106),(1053,127),(1061,151),(1036,172),(752,179),(736,165)],
 baseline=[[747,150],[823,122],[973,108],[1054,144]],
 closed=[[260,133.0],[269.8,128.5],[286.5,128.0],[296,131.5]])]

def extract():
    im=Image.open(REFERENCE).convert('RGB')
    assert im.size==(1144,416), 'Reference size changed: remeasure lash coordinates first.'
    assets=HERE/'assets'; assets.mkdir(exist_ok=True)
    for eye in LASHES:
        x0,y0,x1,y1=eye['box']; rgb=np.asarray(im.crop(eye['box']),dtype=np.float32)
        mask=Image.new('L',(x1-x0,y1-y0));ImageDraw.Draw(mask).polygon([(x-x0,y-y0) for x,y in eye['polygon']],fill=255)
        guard=np.asarray(mask.filter(ImageFilter.GaussianBlur(1.5)),dtype=np.float32)/255
        # Soft ink matte, with a smooth dead zone suppressing pink lid shadows.
        # Dark-gray brush highlights remain as low-amplitude color variation.
        matte=np.clip((203-rgb[...,0])/145,0,1)
        matte=np.where(matte>.12, np.clip((matte-.12)/.88,0,1),0)*guard
        color=np.empty_like(rgb);color[:]=(55,36,52)
        sheen=np.clip((rgb[...,0]-59)/3,0,15)*np.clip((120-rgb[...,0])/45,0,1)
        color += sheen[...,None]
        rgba=np.concatenate([color,np.rint(matte[...,None]*255)],axis=-1).astype(np.uint8)
        Image.fromarray(rgba).save(assets/(eye['name']+'-reference-lash.png'))
    (assets/'lash-placement.json').write_text(json.dumps(LASHES,indent=2),encoding='utf-8')
    print('Reference eyelash-only assets prepared; no face skin transferred.')

if __name__=='__main__': extract()
