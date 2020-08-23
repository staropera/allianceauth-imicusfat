# -*- coding: utf-8 -*-
from allianceauth.authentication.decorators import permissions_required
from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveAllianceInfo, EveCharacter, EveCorporationInfo
from allianceauth.eveonline.providers import provider
from allianceauth.services.hooks import get_extension_logger

from collections import OrderedDict

from datetime import datetime, timedelta

from django.db.models import Count
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.crypto import get_random_string

from esi.decorators import token_required
from esi.models import Token

from . import __title__
from .forms import FatLinkForm, ManualFatForm, FlatListForm, ClickFatForm
from .models import IFat, ClickIFatDuration, IFatLink, ManualIFat, DelLog
from .providers import esi
from .tasks import get_or_create_char, process_fats
from .utils import LoggerAddTag

import random


logger = LoggerAddTag(get_extension_logger(__name__), __title__)

if hasattr(settings, 'FAT_AS_PAP'):
    term = 'PAP'
else:
    term = 'FAT'


# Create your views here.
@login_required()
def imicusfat_view(request):
    msg = None

    if 'msg' in request.session:
        msg = request.session.pop('msg')

    chars = CharacterOwnership.objects.filter(user=request.user)
    fats = []

    for char in chars:
        fat = IFat.objects.filter(character=char.character).order_by('ifatlink__ifattime').reverse()[:30]
        char_1 = [char.character.character_name]

        for f in fat:
            char_1.append(f)
        char_1.append(char.character.character_id)
        fats.append(char_1)

    links = IFatLink.objects.order_by('ifattime').reverse()[:10]

    context = {
        'term': term,
        'fats': fats,
        'links': links,
        'msg': msg
    }

    logger.info(
        'Module called by %s',
        request.user
    )

    return render(request, 'imicusfat/imicusfatview.html', context)


@login_required()
def stats(request):
    if request.user.has_perm('imicusfat.stats_corp_other'):
        corps = EveCorporationInfo.objects.all()
        alliances = EveAllianceInfo.objects.all()
        data = {'No Alliance': []}

        for alliance in alliances:
            data[alliance.alliance_name] = [alliance.alliance_id]

        for corp in corps:
            if corp.alliance is None:
                data['No Alliance'].append((corp.corporation_id, corp.corporation_name))
            else:
                data[corp.alliance.alliance_name].append((corp.corporation_id, corp.corporation_name))

    elif request.user.has_perm('imicusfat.stats_corp_own'):
        data = [(request.user.profile.main_character.corporation_id, request.user.profile.main_character.corporation_name)]
    else:
        data = None

    chars = CharacterOwnership.objects.filter(user=request.user)
    months = []

    for char in chars:
        char_l = [char.character.character_name]
        char_fats = IFat.objects.filter(ifatlink__ifattime__year=datetime.now().year)
        char_stats = {}

        for i in range(1, 13):
            char_fat = char_fats.filter(ifatlink__ifattime__month=i).filter(character__id=char.character.id)

            if len(char_fat) is not 0:
                char_stats[str(i)] = char_fat.count()

        char_l.append(char_stats)
        char_l.append(char.character.character_id)
        months.append(char_l)

    context = {
        'term': term,
        'data': data,
        'charstats': months,
        'year': datetime.now().year
    }

    logger.info(
        'Statistics overview called by %s',
        request.user
    )

    return render(request, 'imicusfat/stats_main.html', context)


@login_required()
def stats_char(request, charid, month=None, year=None):
    character = EveCharacter.objects.get(character_id=charid)
    valid = [char.character for char in CharacterOwnership.objects.filter(user=request.user)]

    if character not in valid and not request.user.has_perm("imicusfat.stats_char_other"):
        request.session['msg'] = ('warning', 'You do not have permission to view statistics for that character.')

        return redirect('imicusfat:imicusfat_view')

    if not month or not year:
        request.session['msg'] = ('danger', 'Date information not complete!')

        return redirect('imicusfat:imicusfat_view')

    fats = IFat.objects.filter(character__character_id=charid, ifatlink__ifattime__month=month, ifatlink__ifattime__year=year)

    # Data for Ship Type Pie Chart
    data_ship_type = {}

    for fat in fats:
        if fat.shiptype in data_ship_type.keys():
            continue
        else:
            data_ship_type[fat.shiptype] = fats.filter(shiptype=fat.shiptype).count()

    colors = []

    for _ in data_ship_type.keys():
        bg_color_str = 'rgba({}, {}, {}, 1)'.format(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        colors.append(bg_color_str)

    data_ship_type = [list(data_ship_type.keys()), list(data_ship_type.values()), colors]

    # Data for by Time Line Chart
    data_time = {}

    for i in range(0, 24):
        data_time[i] = fats.filter(ifatlink__ifattime__hour=i).count()

    data_time = [list(data_time.keys()), list(data_time.values()),
                 ['rgba({}, {}, {}, 1)'.format(random.randint(0, 255),random.randint(0, 255), random.randint(0, 255))]]

    context = {
        'term': term,
        'character': character.character_name,
        'month': month,
        'year': year,
        'data_ship_type': data_ship_type,
        'data_time': data_time,
        'fats': fats
    }

    logger.info(
        'Character statistics called by %s',
        request.user
    )

    return render(request, 'imicusfat/char_stat.html', context)


@login_required()
@permissions_required(('imicusfat.stats_corp_own', 'imicusfat.stats_corp_other'))
def stats_corp(request, corpid, month=None, year=None):
    # Check character has permission to view other corp stats
    if int(request.user.profile.main_character.corporation_id) != int(corpid):
        if not request.user.has_perm("imicusfat.stats_corp_other"):
            request.session['msg'] = ('warning', 'You do not have permission to view statistics for that corporation.')

            return redirect('imicusfat:imicusfat_view')

    corp = EveCorporationInfo.objects.get(corporation_id=corpid)
    corp_name = corp.corporation_name

    if not month and not year:
        year = datetime.now().year
        months = []

        for i in range(1, 13):
            corp_fats = IFat.objects.filter(character__corporation_id=corpid, ifatlink__ifattime__month=i, ifatlink__ifattime__year=year).count()

            if corp_fats is not 0:
                months.append((i, corp_fats))

        context = {
            'term': term,
            'corporation': corp.corporation_name,
            'months': months,
            'corpid': corpid,
            'year': year,
            'type': 0
        }

        return render(request, 'imicusfat/date_select.html', context)

    fats = IFat.objects.filter(ifatlink__ifattime__month=month, ifatlink__ifattime__year=year, character__corporation_id=corpid)
    characters = EveCharacter.objects.filter(corporation_id=corpid)

    # Data for Stacked Bar Graph
    # (label, color, [list of data for stack])
    data = {}

    for fat in fats:
        if fat.shiptype in data.keys():
            continue
        else:
            data[fat.shiptype] = {}

    chars = []

    for fat in fats:
        if fat.character.character_name in chars:
            continue
        else:
            chars.append(fat.character.character_name)

    for key, ship_type in data.items():
        for char in chars:
            ship_type[char] = 0

    for fat in fats:
        data[fat.shiptype][fat.character.character_name] += 1

    data_stacked = []

    for key, value in data.items():
        stack = []
        stack.append(key)
        stack.append('rgba({}, {}, {}, 1)'.format(random.randint(0, 255),
                                                  random.randint(0, 255),
                                                  random.randint(0, 255)))
        stack.append([])
        data_ = stack[2]

        for char in chars:
            data_.append(value[char])

        stack.append(data_)
        data_stacked.append(tuple(stack))

    data_stacked = [chars, data_stacked]

    # Data for By Time
    data_time = {}

    for i in range(0, 24):
        data_time[i] = fats.filter(ifatlink__ifattime__hour=i).count()

    data_time = [list(data_time.keys()), list(data_time.values()),
                 ['rgba({}, {}, {}, 1)'.format(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))]]

    # Data for By Weekday
    data_weekday = []

    for i in range(1, 8):
        data_weekday.append(fats.filter(ifatlink__ifattime__week_day=i).count())

    data_weekday = [['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
                    data_weekday, ['rgba({}, {}, {}, 1)'.format(random.randint(0, 255),
                                                                random.randint(0, 255),
                                                                random.randint(0, 255))]]

    chars = {}

    for char in characters:
        fat_c = fats.filter(character_id=char.id).count()
        chars[char.character_name] = (fat_c, char.character_id)

    context = {
        'term': term,
        'corporation': corp.corporation_name,
        'month': month,
        'year': year,
        'data_stacked': data_stacked,
        'data_time': data_time,
        'data_weekday': data_weekday,
        'chars': chars
    }

    logger.info(
        'Corporation statistics for %s called by %s',
        corp_name,
        request.user
    )

    return render(request, 'imicusfat/corp_stat.html', context)


@login_required()
@permission_required('imicusfat.stats_corp_other')
def stats_alliance(request, allianceid, month=None, year=None):
    if allianceid == '000':
        allianceid = None

    if allianceid is not None:
        ally = EveAllianceInfo.objects.get(alliance_id=allianceid)
        alliance_name = ally.alliance_name
    else:
        ally = None
        alliance_name = "No Alliance"

    if not month and not year:
        year = datetime.now().year
        months = []

        for i in range(1, 13):
            ally_fats = IFat.objects.filter(character__alliance_id=allianceid, ifatlink__ifattime__month=i, ifatlink__ifattime__year=year).count()

            if ally_fats is not 0:
                months.append((i, ally_fats))

        context = {
            'term': term,
            'alliance': alliance_name,
            'months': months,
            'corpid': allianceid,
            'year': year,
            'type': 1
        }

        return render(request, 'imicusfat/date_select.html', context)

    if not month or not year:
        request.session['msg'] = ('danger', 'Date information incomplete.')

        return redirect('imicusfat:imicusfat_view')

    fats = IFat.objects.filter(character__alliance_id=allianceid,
                              ifatlink__ifattime__month=month,
                              ifatlink__ifattime__year=year)

    corporations = EveCorporationInfo.objects.filter(alliance=ally)

    # Data for Ship Type Pie Chart
    data_ship_type = {}

    for fat in fats:
        if fat.shiptype in data_ship_type.keys():
            continue
        else:
            data_ship_type[fat.shiptype] = fats.filter(shiptype=fat.shiptype).count()

    colors = []

    for _ in data_ship_type.keys():
        bg_color_str = 'rgba({}, {}, {}, 1)'.format(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
        colors.append(bg_color_str)

    data_ship_type = [list(data_ship_type.keys()), list(data_ship_type.values()), colors]

    # Fats by corp and ship type?
    data = {}

    for fat in fats:
        if fat.shiptype in data.keys():
            continue
        else:
            data[fat.shiptype] = {}

    corps = []

    for fat in fats:
        if fat.character.corporation_name in corps:
            continue
        else:
            corps.append(fat.character.corporation_name)

    for key, ship_type in data.items():
        for corp in corps:
            ship_type[corp] = 0

    for fat in fats:
        data[fat.shiptype][fat.character.corporation_name] += 1

    if None in data.keys():
        data['Unknown'] = data[None]
        data.pop(None)

    data_stacked = []

    for key, value in data.items():
        stack = []
        stack.append(key)
        stack.append('rgba({}, {}, {}, 1)'.format(random.randint(0, 255),
                                                  random.randint(0, 255),
                                                  random.randint(0, 255)))
        stack.append([])
        data_ = stack[2]

        for corp in corps:
            data_.append(value[corp])

        stack.append(data_)
        data_stacked.append(tuple(stack))

    data_stacked = [corps, data_stacked]

    # Avg fats by corp
    data_avgs = {}

    for corp in corporations:
        c_fats = fats.filter(character__corporation_id=corp.corporation_id).count()
        avg = c_fats/corp.member_count
        data_avgs[corp.corporation_name] = round(avg, 2)

    data_avgs = OrderedDict(sorted(data_avgs.items(), key=lambda x: x[1], reverse=True))
    data_avgs = [list(data_avgs.keys()), list(data_avgs.values()), 'rgba({}, {}, {}, 1)'.format(random.randint(0, 255),
                                                                                           random.randint(0, 255),
                                                                                           random.randint(0, 255))]

    # Fats by Time
    data_time = {}

    for i in range(0, 24):
        data_time[i] = fats.filter(ifatlink__ifattime__hour=i).count()

    data_time = [list(data_time.keys()), list(data_time.values()),
                 ['rgba({}, {}, {}, 1)'.format(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))]]

    # Fats by weekday
    data_weekday = []

    for i in range(1, 8):
        data_weekday.append(fats.filter(ifatlink__ifattime__week_day=i).count())

    data_weekday = [['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
                    data_weekday, ['rgba({}, {}, {}, 1)'.format(random.randint(0, 255),
                                                                random.randint(0, 255),
                                                                random.randint(0, 255))]]

    # Corp list
    corps = {}

    for corp in corporations:
        c_fats = fats.filter(character__corporation_id=corp.corporation_id).count()
        avg = c_fats/corp.member_count
        corps[corp] = (corp.corporation_id, c_fats, round(avg, 2))

    corps = OrderedDict(sorted(corps.items(), key=lambda x: x[1][2], reverse=True))

    context = {
        'term': term,
        'alliance': alliance_name,
        'month': month,
        'year': year,
        'data_stacked': data_stacked,
        'data_avgs': data_avgs,
        'data_time': data_time,
        'data_weekday': data_weekday,
        'corps': corps,
        'data_ship_type': data_ship_type
    }

    logger.info(
        'Alliance statistics for %s called by %s',
        alliance_name,
        request.user
    )

    return render(request, 'imicusfat/ally_stat.html', context)


@login_required()
def links(request):

    msg = None

    if 'msg' in request.session:
        msg = request.session.pop('msg')

    links = IFatLink.objects.filter(ifat__deleted_at__isnull=True).order_by(
        '-ifattime').annotate(number_of_fats=Count('ifat'))

    context = {
        'term': term,
        'links': links,
        'msg': msg
    }

    logger.info(
        'FAT link list called by %s',
        request.user
    )

    return render(request, 'imicusfat/fat_list.html', context)


@login_required()
@permissions_required(('imicusfat.manage_imicusfat', 'imicusfat.add_ifatlink'))
def link_add(request):
    context = {
        'term': term
    }

    logger.info(
        'Add FAT link view called by %s',
        request.user
    )

    return render(request, 'imicusfat/addlink.html', context)


@login_required()
@permissions_required(('imicusfat.manage_imicusfat', 'imicusfat.add_ifatlink'))
def link_create_click(request):
    if request.method == "POST":
        form = ClickFatForm(request.POST)

        if form.is_valid():
            hash = get_random_string(length=30)
            link = IFatLink()
            link.fleet = form.cleaned_data['name']
            link.creator = request.user
            link.hash = hash
            link.save()
            dur = ClickIFatDuration()
            dur.fleet = IFatLink.objects.get(hash=hash)
            dur.duration = form.cleaned_data['duration']
            dur.save()

            request.session['{}-creation-code'.format(hash)] = 202

            logger.info(
                'FAT link %s with name %s and a duration of %s minutes was created by %s',
                hash,
                form.cleaned_data['name'],
                form.cleaned_data['duration'],
                request.user
            )

            return redirect('imicusfat:link_edit', hash=hash)
        else:
            request.session['msg'] = ['danger', ('Something went wrong when attempting to submit your'
                                                 ' clickable {0}Link.'.format(term))]
            return redirect('imicusfat:imicusfat_view')
    else:
        request.session['msg'] = ['warning',
                                  ('You must fill out the form on the "Add {0}Link" '
                                   'page to create a clickable {0}Link'.format(term))]

        return redirect('imicusfat:imicusfat_view')


@login_required()
@permissions_required(('imicusfat.manage_imicusfat', 'imicusfat.add_ifatlink'))
@token_required(scopes=['esi-fleets.read_fleet.v1'])
def link_create_esi(request, token):
    # "error": "The fleet does not exist or you don't have access to it!"
    hash = get_random_string(length=30)
    link = IFatLink(fleet=None, creator=request.user, hash=hash)
    link.save()

    # Check if there is a fleet
    try:
        requiredScopes = ['esi-fleets.read_fleet.v1']
        esiToken = Token.get_token(token.character_id, requiredScopes)

        f = esi.client.Fleets.get_characters_character_id_fleet(
            character_id=token.character_id,
            token = esiToken.valid_access_token()
        ).result()

        try:
            fleet = esi.client.Fleets.get_fleets_fleet_id(
                fleet_id = f['fleet_id'],
                token = esiToken.valid_access_token()
            ).result()

            m = esi.client.Fleets.get_fleets_fleet_id_members(
                fleet_id = f['fleet_id'],
                token = esiToken.valid_access_token()
            ).result()

            process_fats.delay(m, 'eve', hash)

            request.session['{}-creation-code'.format(hash)] = 200

            logger.info(
                'ESI FAT link %s created by %s',
                hash,
                request.user
            )

            return redirect('imicusfat:link_edit', hash=hash)
        except Exception:
            request.session['{}-creation-code'.format(hash)] = 403

            return redirect('imicusfat:link_edit', hash=hash)
    except Exception:
        request.session['{}-creation-code'.format(hash)] = 404

        return redirect('imicusfat:link_edit', hash=hash)


@login_required()
@token_required(scopes=['esi-location.read_location.v1', 'esi-location.read_ship_type.v1'])
def click_link(request, token, hash=None):
    if hash is None:
        request.session['msg'] = ['warning', 'No {}link hash provided.'.format(term)]

        return redirect('imicusfat:imicusfat_view')

    try:
        try:
            fleet = IFatLink.objects.get(hash=hash)
        except Exception:
            request.session['msg'] = ['warning', 'The hash provided is not valid.']

            return redirect('imicusfat:imicusfat_view')

        dur = ClickIFatDuration.objects.get(fleet=fleet)
        now = timezone.now()-timedelta(minutes=dur.duration)

        if now >= fleet.ifattime:
            request.session['msg'] = ['warning', ('Sorry, that {0}Link is expired. If you were on that fleet, '
                                                  'contact your FC about having your {0} manually added.'.format(term))]
            return redirect('imicusfat:imicusfat_view')

        character = EveCharacter.objects.get(character_id=token.character_id)

        try:
            requiredScopes = ['esi-location.read_location.v1', 'esi-location.read_ship_type.v1']
            esiToken = Token.get_token(token.character_id, requiredScopes)

            location = esi.client.Location.get_characters_character_id_location(
                character_id = token.character_id,
                token = esiToken.valid_access_token()
            ).result()

            ship = esi.client.Location.get_characters_character_id_ship(
                character_id = token.character_id,
                token = esiToken.valid_access_token()
            ).result()

            location = esi.client.Universe.get_universe_systems_system_id(system_id=location['solar_system_id']).result()['name']

            ship = provider.get_itemtype(ship['ship_type_id']).name

            try:
                fat = IFat(ifatlink=fleet, character=character, system=location, shiptype=ship)
                fat.save()

                if fleet.fleet is not None:
                    name = fleet.fleet
                else:
                    name = fleet.hash

                request.session['msg'] = ['success', ('{} registered for {} at {}'.format(term,
                                                                                          character.character_name,
                                                                                          name))]

                logger.info(
                    'Fleetparticipation for fleet %s registered for pilot %s',
                    name,
                    character.character_name
                )

                return redirect('imicusfat:imicusfat_view')
            except Exception:
                request.session['msg'] = ['warning', ('A {} already exists for the selected character ({}) and fleet'
                                                      ' combination.'.format(term, character.character_name))]
                return redirect('imicusfat:imicusfat_view')
        except Exception:
            request.session['msg'] = ['warning', ('There was an issue with the token for {}.'
                                                  ' Please try again.'.format(character.character_name))]
            return redirect('imicusfat:imicusfat_view')
    except Exception:
        request.session['msg'] = ['warning', 'The hash provided is not for a clickable {}Link.'.format(term)]

        return redirect('imicusfat:imicusfat_view')


@login_required()
@permissions_required(('imicusfat.manage_imicusfat', 'imicusfat.add_ifatlink', 'imicusfat.change_ifatlink'))
def edit_link(request, hash=None):
    if hash is None:
        request.session['msg'] = ['warning', 'No {}link hash provided.'.format(term)]

        return redirect('imicusfat:imicusfat_view')

    try:
        link = IFatLink.objects.get(hash=hash)
    except Exception:
        request.session['msg'] =['warning', 'The hash provided is not valid.']

        return redirect('imicusfat:imicusfat_view')

    debug = None

    if request.method == "POST":
        f1 = FatLinkForm(request.POST)
        f2 = FlatListForm(request.POST)
        f3 = ManualFatForm(request.POST)

        if f1.is_valid():
            link.fleet = request.POST['fleet']
            link.save()
            request.session['{}-task-code'.format(hash)] = 1
        elif f2.is_valid():
            flatlist = request.POST['flatlist']
            formatted = flatlist.replace("\r", "").split("\n")
            process_fats.delay(formatted, 'flatlist', hash)
            request.session['{}-task-code'.format(hash)] = 2
        elif f3.is_valid():
            form = request.POST
            character_name = form['character']
            system = form['system']
            shiptype = form['shiptype']
            creator = request.user
            character = get_or_create_char(name=character_name)

            if character is not None:
                fat = IFat(ifatlink_id=link.pk, character=character, system=system, shiptype=shiptype).save()
                ManualIFat(ifatlink_id=link.pk, creator=creator, character=character).save()
                request.session['{}-task-code'.format(hash)] = 3
            else:
                request.session['{}-task-code'.format(hash)] = 4
        else:
            request.session['{}-task-code'.format(hash)] = 0

    msg = None

    if '{}-creation-code'.format(hash) in request.session:
        msg = request.session.pop('{}-creation-code'.format(hash))
    elif '{}-task-code'.format(hash) in request.session:
        msg = request.session.pop('{}-task-code'.format(hash))

    fats = IFat.objects.filter(ifatlink=link)
    flatlist = None

    if len(fats) > 0:
        flatlist = []

        for fat in fats:
            fatinfo = [fat.character.character_name, str(fat.system), str(fat.shiptype)]
            flatlist.append("\t".join(fatinfo))

        flatlist = "\r\n".join(flatlist)

    context = {
        'term': term,
        'form': FatLinkForm,
        'msg': msg,
        'link': link,
        'fats': fats,
        'flatlist': flatlist,
        'debug': debug
    }

    logger.info(
        'FAT link %s edited by %s',
        hash,
        request.user
    )

    return render(request, 'imicusfat/fleet_edit.html', context)

@login_required()
@permissions_required(('imicusfat.manage_imicusfat', 'imicusfat.delete_ifatlink'))
def del_link(request, hash=None):
    if hash is None:
        request.session['msg'] = ['warning', 'No {}link hash provided.'.format(term)]
        return redirect('imicusfat:imicusfat_view')

    try:
        link = IFatLink.objects.get(hash=hash)
    except Exception:
        request.session['msg'] = ['danger', 'The hash provided is either invalid or has been deleted.']

        return redirect('imicusfat:imicusfat_view')

    fats = IFat.objects.filter(ifatlink_id=link.pk).delete()

    link.delete()
    DelLog(remover=request.user, deltype=0, string=link.__str__()).save()
    request.session['msg'] = ['success', 'The {0}Link ({1}) and all associated {0}s have been successfully deleted.'.format(term, hash)]

    logger.info(
        'FAT link %s deleted by %s',
        hash,
        request.user
    )

    context = {
        'msg': request.session['msg']
    }

    # return render(request, 'imicusfat/fat_list.html', context)

    return redirect('imicusfat:links')


@login_required()
@permissions_required(('imicusfat.manage_imicusfat', 'imicusfat.delete_ifat'))
def del_fat(request, hash, fat):
    try:
        link = IFatLink.objects.get(hash=hash)
    except Exception:
        request.session['msg'] = ['danger', 'The hash provided is either invalid or has been deleted.']

        return redirect('imicusfat:imicusfat_view')

    try:
        fat = IFat.objects.get(pk=fat, ifatlink_id=link.pk)
    except Exception:
        request.session['msg'] = ['danger', 'The hash and {} ID do not match.'.format(term)]

        return redirect('imicusfat:imicusfat_view')

    fat.delete()

    DelLog(remover=request.user, deltype=1, string=fat.__str__())
    request.session['msg'] = ['success', 'The {0} for {0} from link {1} has been successfully deleted.'.format(term, hash)]

    logger.info(
        'FAT %s deleted by %s',
        fat,
        request.user
    )

    return redirect('imicusfat:imicusfat_view')
