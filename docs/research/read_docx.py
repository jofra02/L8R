
import zipfile
import xml.etree.ElementTree as ET
import sys
import os

def read_docx(file_path):
    try:
        with zipfile.ZipFile(file_path) as z:
            xml_content = z.read('word/document.xml')
        
        # Parse XML
        root = ET.fromstring(xml_content)
        
        # Namespace for Word
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        
        full_text = []
        for p in root.findall('.//w:p', ns):
            para_text = []
            for r in p.findall('.//w:r', ns):
                for t in r.findall('.//w:t', ns):
                    if t.text:
                        para_text.append(t.text)
            if para_text:
                full_text.append(''.join(para_text))
        
        return '\n'.join(full_text)
    except Exception as e:
        return f"Error reading docx: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python read_docx.py <input_file> [output_file]")
        sys.exit(1)
    
    file_path = sys.argv[1]
    content = read_docx(file_path)
    
    if len(sys.argv) > 2:
        output_path = sys.argv[2]
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        print(content)
