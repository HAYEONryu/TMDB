const employeePages=new Set(['/app/employee','/app/employee/today','/app/employee/mine','/app/guides']);

// Carry an explicit non-default site through both the menu and dashboard links.
// Keep the default URL behavior and never change the global site setting.
export function syncEmployeeSiteLinks(site,defaultSite){
  for(const link of document.querySelectorAll('a[href]')){
    const url=new URL(link.href,location.href);
    if(url.origin!==location.origin||!employeePages.has(url.pathname))continue;
    if(site&&site!==defaultSite)url.searchParams.set('site_id',site);
    else url.searchParams.delete('site_id');
    link.href=url.pathname+url.search+url.hash;
  }
}
