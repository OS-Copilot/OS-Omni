"""Offline schematic basemap using recovered place coordinates, not road imagery."""
import io
import math
from PIL import Image, ImageDraw

def tile_coordinates(latitude,longitude,zoom):
    scale=2**zoom
    latitude=max(-85.0511,min(85.0511,latitude))
    return ((longitude+180)/360*scale,(1-math.asinh(math.tan(math.radians(latitude)))/math.pi)/2*scale)

def render_tile(zoom,x,y,places):
    image=Image.new('RGB',(256,256),(239,243,237))
    draw=ImageDraw.Draw(image)
    for offset in range(0,257,64):
        draw.line((offset,0,offset,256),fill=(207,216,207),width=1)
        draw.line((0,offset,256,offset),fill=(207,216,207),width=1)
    draw.text((4,4),f'Local schematic z{zoom}',fill=(99,113,99))
    draw.text((4,240),'Reconstructed coordinate grid',fill=(99,113,99))
    for place in places:
        px,py=tile_coordinates(place['latitude'],place['longitude'],zoom)
        px=(px-x)*256;py=(py-y)*256
        if -10<=px<266 and -10<=py<266:
            draw.ellipse((px-4,py-4,px+4,py+4),fill=(60,104,159))
            draw.text((max(2,min(160,px+6)),max(20,min(220,py-6))),place['address'].split(',')[0][:28],fill=(38,58,75))
    buffer=io.BytesIO();image.save(buffer,format='PNG');return buffer.getvalue()
