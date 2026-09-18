website = env['website'].browse(1)
company = env.company
# Code <head> personnalisé du site mc2 (icônes Remix Icon et Bootstrap Icons par CDN), repris tel quel.
website.write({'custom_code_head': '<link\n    href="https://cdn.jsdelivr.net/npm/remixicon@4.7.0/fonts/remixicon.css"\n    rel="stylesheet"\n/>\n<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.13.1/font/bootstrap-icons.min.css">', 'logo': company.logo})
env.cr.commit()
print('head code chars:', len(website.custom_code_head or ''), '| website logo set:', bool(website.logo), '| homepage:', website.homepage_url)
