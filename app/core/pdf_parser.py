import pymupdf

doc = pymupdf.open("document.pdf")
for page in doc:
    print(page.get_text())