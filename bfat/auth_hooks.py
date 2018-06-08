from . import urls
from django.utils.translation import ugettext_lazy as _
from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook


@hooks.register('menu_item_hook')
def register_menu():
    return MenuItemHook(_('Fleet Activity Tracking'), 'fas fa-crosshairs', 'bfat:bfat_view',
                        navactive=['bfat:'])


@hooks.register('url_hook')
def register_url():
    return UrlHook(urls, 'bfat', r'^bfat/')