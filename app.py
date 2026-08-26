import os, re, json, html
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
API_VERSION = '2026-07'
UA = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148 Safari/537.36'}

def clean(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()

def absolute_images(soup):
    out=[]
    for tag in soup.find_all(['meta','img']):
        u=None
        if tag.name=='meta' and tag.get('property') in ('og:image','twitter:image'):
            u=tag.get('content')
        elif tag.name=='img':
            u=tag.get('src') or tag.get('data-src') or tag.get('data-lazy-src')
        if u and u.startswith('//'): u='https:'+u
        if u and u.startswith('http') and u not in out: out.append(u)
    return out[:16]

def extract_product(url):
    result={'source_url':url,'title':'','description':'','price':'','currency':'','images':[],'raw_text':''}
    errors=[]
    try:
        r=requests.get(url,headers=UA,timeout=20,allow_redirects=True)
        r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser')
        title=soup.find('meta',property='og:title')
        result['title']=clean(title.get('content') if title else (soup.title.string if soup.title else ''))
        desc=soup.find('meta',property='og:description') or soup.find('meta',attrs={'name':'description'})
        result['description']=clean(desc.get('content') if desc else '')
        result['images']=absolute_images(soup)
        result['raw_text']=clean(soup.get_text(' ',strip=True))[:24000]
        for sc in soup.find_all('script',type='application/ld+json'):
            try:
                data=json.loads(sc.string or '{}'); items=data if isinstance(data,list) else [data]
                for item in items:
                    if isinstance(item,dict) and item.get('@type')=='Product':
                        result['title']=result['title'] or clean(item.get('name'))
                        result['description']=result['description'] or clean(item.get('description'))
                        ims=item.get('image') or []
                        if isinstance(ims,str): ims=[ims]
                        result['images']=(ims+result['images'])[:16]
                        off=item.get('offers'); off=off[0] if isinstance(off,list) and off else off
                        if isinstance(off,dict):
                            result['price']=str(off.get('price') or result['price']); result['currency']=off.get('priceCurrency') or result['currency']
            except Exception: pass
        if not result['price']:
            m=re.search(r'(?:(?:US\s*)?\$|USD\s*)(\d+(?:[.,]\d{1,2})?)',result['raw_text'],re.I)
            if m: result['price']=m.group(1).replace(',','.'); result['currency']='USD'
        if result['title'] and result['images']: return result, errors
    except Exception as e: errors.append('Direct fetch: '+str(e))
    try:
        ju='https://r.jina.ai/http://'+url.replace('https://','',1).replace('http://','',1)
        rr=requests.get(ju,headers=UA,timeout=30); rr.raise_for_status(); txt=rr.text
        result['raw_text']=txt[:30000]
        mt=re.search(r'^Title:\s*(.+)$',txt,re.M)
        if mt: result['title']=clean(mt.group(1))
        imgs=re.findall(r'!\[[^\]]*\]\((https?://[^)]+)\)',txt)
        result['images']=list(dict.fromkeys(imgs))[:16]
        if not result['price']:
            m=re.search(r'(?:(?:US\s*)?\$|USD\s*)(\d+(?:[.,]\d{1,2})?)',txt,re.I)
            if m: result['price']=m.group(1).replace(',','.'); result['currency']='USD'
    except Exception as e: errors.append('Reader fallback: '+str(e))
    return result, errors

def ai_generate(product, cfg):
    lang=cfg.get('language') or 'ar'; tone='Arabic suitable for Iraqi ecommerce buyers' if lang=='ar' else 'clear conversion-focused English'
    schema='{"title":"","subtitle":"","badge":"","benefits":["","",""],"feature_blocks":[{"heading":"","body":""}],"how_to":[""],"faq":[{"q":"","a":""}],"shipping":"","guarantee":"","cta":"","seo_title":"","seo_description":""}'
    prompt=f"You are an ecommerce conversion copywriter. Build a polished product page from the source data below. Do not invent medical, safety, certification, warranty, or performance claims not supported by source. Write in {tone}. Return ONLY valid JSON matching this schema exactly: {schema}\nSOURCE TITLE: {product.get('title')}\nSOURCE DESCRIPTION: {product.get('description')}\nSOURCE PRICE: {product.get('price')} {product.get('currency')}\nSOURCE TEXT: {product.get('raw_text','')[:12000]}"
    provider=cfg.get('provider') or os.getenv('AI_PROVIDER','gemini')
    key=(cfg.get('api_key') or os.getenv('AI_API_KEY','')).strip()
    model=cfg.get('model') or os.getenv('AI_MODEL','gemini-2.5-flash')
    if not key: raise ValueError('AI API key is required')
    if provider=='gemini':
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
        payload={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'responseMimeType':'application/json','temperature':0.5}}
        r=requests.post(url,json=payload,timeout=60); r.raise_for_status(); text=r.json()['candidates'][0]['content']['parts'][0]['text']
    else:
        base=(cfg.get('base_url') or os.getenv('OPENAI_BASE_URL','https://api.openai.com/v1')).rstrip('/')
        r=requests.post(base+'/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json={'model':model,'messages':[{'role':'user','content':prompt}],'temperature':0.5},timeout=60); r.raise_for_status(); text=r.json()['choices'][0]['message']['content']
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip(),flags=re.S)
    return json.loads(text)

def page_html(p, copy):
    direction='rtl' if any('\u0600' <= c <= '\u06ff' for c in (copy.get('title','')+copy.get('subtitle',''))) else 'ltr'
    imgs=p.get('images') or []; hero=imgs[0] if imgs else ''
    benefits=''.join(f'<li>{html.escape(str(x))}</li>' for x in copy.get('benefits',[]))
    blocks=''.join(f"<section><h2>{html.escape(str(x.get('heading','')))}</h2><p>{html.escape(str(x.get('body','')))}</p></section>" for x in copy.get('feature_blocks',[]))
    faq=''.join(f"<details><summary>{html.escape(str(x.get('q','')))}</summary><p>{html.escape(str(x.get('a','')))}</p></details>" for x in copy.get('faq',[]))
    hero_html = f'<img src="{html.escape(hero)}" alt="" style="width:100%;border-radius:18px">' if hero else ''
    return f'<div dir="{direction}" style="font-family:Arial,sans-serif;max-width:980px;margin:auto;line-height:1.7;color:#181818"><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:28px;align-items:center;padding:20px 0"><div>{hero_html}</div><div><div style="display:inline-block;background:#111;color:#fff;padding:6px 12px;border-radius:999px">{html.escape(copy.get("badge",""))}</div><h1 style="font-size:38px;line-height:1.15">{html.escape(copy.get("title",""))}</h1><p style="font-size:19px">{html.escape(copy.get("subtitle",""))}</p><p style="font-size:27px;font-weight:700">{html.escape(str(p.get("price","")))} {html.escape(p.get("currency",""))}</p><a href="#buy" style="display:block;text-align:center;background:#111;color:white;padding:15px;border-radius:12px;text-decoration:none;font-weight:700">{html.escape(copy.get("cta","Buy now"))}</a></div></div><section><ul style="font-size:18px">{benefits}</ul></section>{blocks}<section><h2>FAQ</h2>{faq}</section><section><h2>Shipping</h2><p>{html.escape(copy.get("shipping",""))}</p></section><section><h2>{html.escape(copy.get("guarantee",""))}</h2></section></div>'

def shopify_graphql(shop, token, query, variables):
    shop=(shop or os.getenv('SHOPIFY_STORE','')).replace('https://','').replace('http://','').strip('/ ')
    token=token or os.getenv('SHOPIFY_TOKEN','')
    if not shop or not token: raise ValueError('Shopify store and token are required')
    if not shop.endswith('.myshopify.com'): shop += '.myshopify.com'
    r=requests.post(f'https://{shop}/admin/api/{API_VERSION}/graphql.json',headers={'X-Shopify-Access-Token':token,'Content-Type':'application/json'},json={'query':query,'variables':variables},timeout=60)
    r.raise_for_status(); data=r.json()
    if data.get('errors'): raise ValueError(str(data['errors']))
    return data['data']

@app.get('/')
def index(): return render_template('index.html')
@app.get('/health')
def health(): return {'ok':True}
@app.post('/api/import')
def api_import():
    url=(request.json or {}).get('url','').strip()
    if not url.startswith(('http://','https://')): return jsonify(error='Enter a valid product URL'),400
    p, errors=extract_product(url); return jsonify(product=p,warnings=errors)
@app.post('/api/generate')
def api_generate():
    data=request.json or {}; p=data.get('product') or {}; cfg=data.get('ai') or {}
    try:
        copy=ai_generate(p,cfg); return jsonify(copy=copy,html=page_html(p,copy))
    except Exception as e: return jsonify(error=str(e)),400
@app.post('/api/shopify/test')
def api_shop_test():
    d=request.json or {}
    try:
        q='query { shop { name myshopifyDomain } publications(first:20) { nodes { id name } } }'
        return jsonify(data=shopify_graphql(d.get('shop',''),d.get('token',''),q,{}))
    except Exception as e: return jsonify(error=str(e)),400
@app.post('/api/shopify/publish')
def api_shop_publish():
    d=request.json or {}; p=d.get('product') or {}; copy=d.get('copy') or {}; s=d.get('shopify') or {}
    try:
        desc=page_html(p,copy)
        media=[{'originalSource':u,'alt':copy.get('title') or p.get('title') or 'Product image','mediaContentType':'IMAGE'} for u in (p.get('images') or [])[:10] if u.startswith('http')]
        q='mutation Create($product: ProductCreateInput!, $media: [CreateMediaInput!]) { productCreate(product:$product, media:$media){ product { id handle variants(first:1){nodes{id}} } userErrors { field message } } }'
        inp={'title':copy.get('title') or p.get('title') or 'Product','descriptionHtml':desc,'status':'ACTIVE' if s.get('activate') else 'DRAFT'}
        res=shopify_graphql(s.get('shop',''),s.get('token',''),q,{'product':inp,'media':media})['productCreate']
        if res['userErrors']: raise ValueError(str(res['userErrors']))
        prod=res['product']; price=str(p.get('price') or '').strip()
        if price and prod['variants']['nodes']:
            q2='mutation U($productId:ID!,$variants:[ProductVariantsBulkInput!]!){productVariantsBulkUpdate(productId:$productId,variants:$variants){userErrors{field message}}}'
            up=shopify_graphql(s.get('shop',''),s.get('token',''),q2,{'productId':prod['id'],'variants':[{'id':prod['variants']['nodes'][0]['id'],'price':price}]})['productVariantsBulkUpdate']
            if up['userErrors']: raise ValueError(str(up['userErrors']))
        return jsonify(product=prod)
    except Exception as e: return jsonify(error=str(e)),400

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.getenv('PORT','8787')))
