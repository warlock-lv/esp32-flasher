from PIL import Image
import sys, os

if len(sys.argv) < 2:
    print("用法: python png2ico.py app_exe.png")
    sys.exit(1)

input_file = sys.argv[1]
output_file = os.path.splitext(input_file)[0] + ".ico"

img = Image.open(input_file)

# 常见尺寸集合
sizes = [(16,16), (32,32), (48,48), (128,128), (256,256)]

img.save(output_file, format="ICO", sizes=sizes)

print(f"[✓] 已生成多尺寸 ICO 文件: {output_file}")
