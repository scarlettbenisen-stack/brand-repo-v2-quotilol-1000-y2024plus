#!/usr/bin/env python3
"""
Enrich manifest.json with author handles and update index.html
"""

import json
import re

# Provided tweet_id -> handle mapping
AUTHOR_MAPPING = {
    '2027786026551226808': 'kyleanthony',
    '2027747047072231550': 'thenickpattison',
    '2027443136327520571': 'pizzaboy',
    '2027067841149542885': 'creativemints',
    '2026718950176993311': 'LucieBajgart',
    '2027059273960653254': 'GotinGeorgiG',
    '2026989064902041817': 'rebrandgallery',
    '2026537645959270516': 'lifeofmansoor',
    '2026619045336994173': 'devxnuj',
    '2025962848820584782': 'JulienRenvoye',
    '2026254672567173479': 'rebrandgallery',
    '2026213072776667491': 'adriankuleszo',
    '2026192287756349922': 'socoloffalex',
    '2026015967998877893': 'kyleanthony',
    '2026597820359213329': 'brandarchivexyz',
    '2026322476427248012': 'ivanboroja',
    '2025995405159244079': 'rebrandgallery'
}

def enrich_manifest():
    """Enrich manifest.json with author_handle field"""
    
    # Read manifest
    with open('input/manifest.json', 'r') as f:
        manifest = json.load(f)
    
    # Count stats
    total_items = len(manifest['items'])
    matched_count = 0
    
    # Add author_handle field
    for item in manifest['items']:
        tweet_id = item['tweet_id']
        if tweet_id in AUTHOR_MAPPING:
            item['author_handle'] = AUTHOR_MAPPING[tweet_id]
            matched_count += 1
    
    # Write updated manifest
    with open('input/manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)
    
    return total_items, matched_count

def update_index_html():
    """Update index.html to display author handles and add author filter"""
    
    with open('index.html', 'r') as f:
        content = f.read()
    
    # Add author filter dropdown after the existing filters
    author_filter_html = '''<select id="author"><option value="all">Author: all</option></select>'''
    
    # Insert after the last filter
    last_filter_pos = content.rfind('</select>')
    if last_filter_pos != -1:
        insert_pos = content.find('\n', last_filter_pos) + 1
        content = content[:insert_pos] + f'        {author_filter_html}\n' + content[insert_pos:]
    
    # Update card template to include author handle
    # Find the file line and add author handle after it
    file_line_pattern = r'(<div class="file" title="[^"]*">[^<]*</div>)'
    author_line = '''<div class="file author" style="color:#8a9bb8; font-size:11px;">@${it.author_handle || 'unknown'}</div>'''
    
    # Replace the file line with file + author
    content = re.sub(file_line_pattern, r'\1\n            ' + author_line, content)
    
    # Update stats display
    stats_pattern = r'stats\.textContent = `([^`]+)`;'
    stats_replacement = r'stats.textContent = `Total brand ${allItems.length} | affichés ${shown.length}${authorFilter ? ` | author: ${authorFilter}` : ""}`;'
    content = re.sub(stats_pattern, stats_replacement, content)
    
    # Add author filter logic to visible function
    visible_pattern = r'function visible\(it\)\{([^}]+)\}'  
    author_filter_logic = '''\n      const authorFilter = controls.author.value;
      if (authorFilter !== 'all' && it.author_handle !== authorFilter) return false;'''
    
    visible_match = re.search(visible_pattern, content, re.DOTALL)
    if visible_match:
        visible_body = visible_match.group(1)
        # Insert author filter after the search filter
        search_pos = visible_body.find('if (q && !it.file.toLowerCase().includes(q)) return false;')
        if search_pos != -1:
            insert_pos = search_pos + len('if (q && !it.file.toLowerCase().includes(q)) return false;')
            new_visible_body = visible_body[:insert_pos] + author_filter_logic + visible_body[insert_pos:]
            content = content.replace(visible_body, new_visible_body)
    
    # Add author filter to controls object
    controls_pattern = r'const controls = \{([^}]+)\}'
    controls_match = re.search(controls_pattern, content)
    if controls_match:
        controls_body = controls_match.group(1)
        # Add author to controls
        controls_body = controls_body.rstrip() + '\n      author: el(\'author\')'
        content = content.replace(controls_match.group(0), f'const controls = {{{controls_body}\n    }};')
    
    # Add author filter event listener
    event_listeners_pattern = r'Object\.values\(controls\)\.forEach\(x => x\.addEventListener\([^)]+\)\)'
    if re.search(event_listeners_pattern, content):
        # Already has event listeners, we're good
        pass
    else:
        # Add after the controls definition
        controls_end_pos = content.find('};', content.find('const controls ='))
        if controls_end_pos != -1:
            insert_pos = controls_end_pos + 2
            event_listeners = '''\n\n    Object.values(controls).forEach(x => x.addEventListener('input', render));\n    Object.values(controls).forEach(x => x.addEventListener('change', render));'''
            content = content[:insert_pos] + event_listeners + content[insert_pos:]
    
    # Add author population logic after data load
    data_load_pattern = r'\.then\(\(\[payload, thumbs\]\) => \{([^}]+)\}\)'
    data_load_match = re.search(data_load_pattern, content, re.DOTALL)
    if data_load_match:
        load_body = data_load_match.group(1)
        # Add author population
        author_population = '''\n        \n        // Populate author filter\n        const authors = [...new Set(allItems.map(it => it.author_handle).filter(Boolean))].sort();\n        const authorSelect = controls.author;\n        authorSelect.innerHTML = '<option value="all">Author: all</option>' + authors.map(author => \n          `<option value="${author}">@${author}</option>`\n        ).join('');'''
        
        # Insert after thumbMeta assignment
        thumb_pos = load_body.find('thumbMeta = thumbs;')
        if thumb_pos != -1:
            insert_pos = thumb_pos + len('thumbMeta = thumbs;')
            new_load_body = load_body[:insert_pos] + author_population + load_body[insert_pos:]
            content = content.replace(load_body, new_load_body)
    
    # Write updated HTML
    with open('index.html', 'w') as f:
        f.write(content)

def main():
    print("Enriching manifest.json with author handles...")
    total_items, matched_count = enrich_manifest()
    print(f"✅ Updated {matched_count}/{total_items} items with author handles")
    
    print("Updating index.html with author display and filter...")
    update_index_html()
    print("✅ Updated index.html")
    
    print(f"\nSummary:")
    print(f"- Manifest items: {total_items}")
    print(f"- Items with author handles: {matched_count}")
    print(f"- Author mapping entries: {len(AUTHOR_MAPPING)}")
    
    return total_items, matched_count

if __name__ == '__main__':
    main()