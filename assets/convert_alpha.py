from PIL import Image
import os
for f in ["arc_reactor", "recon_drone", "helmet"]:
    try:
        img = Image.open(f"assets/{f}.jpg").convert("RGBA")
        data = img.getdata()
        new_data = [(r, g, b, max(r,g,b)) for r, g, b, a in data]
        img.putdata(new_data)
        img.save(f"assets/{f}.png", "PNG")
        print(f"Converted {f}.png")
    except Exception as e:
        print(f"Error on {f}: {e}")
