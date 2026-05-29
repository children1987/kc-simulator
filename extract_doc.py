import urllib.request, re

resp = urllib.request.urlopen('https://opentcs.org/docs/7/user/opentcs-users-guide.html')
html = resp.read().decode('utf-8')

# Simple approach: strip ALL tags, keep text
text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL)
text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL)
text = re.sub(r'<head[^>]*>.*?</head>', '', text, flags=re.DOTALL)
text = re.sub(r'<[^>]+>', ' ', text)
text = re.sub(r'&nbsp;', ' ', text)
text = re.sub(r'&amp;', '&', text)
text = re.sub(r'&lt;', '<', text)
text = re.sub(r'&gt;', '>', text)
text = re.sub(r'\s+', ' ', text)
text = text.replace('​', '')  # zero-width space

# Split on section markers
for section in ['Operating the plant', 'Configuring vehicle drivers', 'Creating a transport order',
                'Automatically selecting a specific vehicle driver', 'Adding elements',
                'Generic properties', 'Vehicle']:
    idx = text.find(section)
    if idx > 0:
        end = min(idx + 5000, len(text))
        print(f'\n{"="*60}')
        print(f'=== {section} (pos={idx}) ===')
        print(f'{"="*60}')
        print(text[idx:end])
        print()
