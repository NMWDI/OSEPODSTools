# ===============================================================================
# Copyright 2022 ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================
import datetime
import math
import os
import sys

import folium
import json
from itertools import groupby
import pyproj
import pandas
import s2sphere
import shapefile
import staticmaps
from PIL import ImageDraw, ImageFont, Image
from PIL.Image import Resampling

from mpl_toolkits.basemap import Basemap
import matplotlib.pyplot as plt
from staticmaps import PillowRenderer

OSE_PODS_HEADER = 'pod_basin|pod_nbr|pod_suffix|ref|pod_name|tws|rng|sec|qtr_4th|qtr_16th|qtr_64th|qtr_256th' \
                  '|qtr_1024th|qtr_4096|blk|zone|x|y|grant|legal|county|license_nbr|driller|start_date|finish_date' \
                  '|plug_date|pcw_rcv_date|elevation|depth_well|grnd_wtr_src|percent_shallow|depth_water' \
                  '|log_file_date|sched_date|usgs_map_code|usgs_map_suffix|usgs_map_quad1|usgs_map_quad2|use_of_well' \
                  '|pump_type|pump_serial|discharge|photo|photo_date|photo_punch|aquifer|sys_date|measure|subdiv_name' \
                  '|subdiv_location|municipality|municipality_loc|restrict|usgs_pod_nbr|lat_deg|lat_min|lat_sec' \
                  '|lon_deg|lon_min|lon_sec|surface_code|estimate_yield|pod_status|casing_size|ditch_name|utm_zone' \
                  '|easting|northing|datum|utm_source|utm_accuracy|xy_source|xy_accuracy|lat_lon_source' \
                  '|lat_lon_accuracy|tract_nbr|map_nbr|surv_map|other_loc|pod_rec_nbr|cfs_start_mday|cfs_end_mday' \
                  '|cfs_cnv_factor|cs_code|wrats_s_id|utm_error|pod_sub_basin|well_tag|static_level '
OSE_PODS_HEADER = OSE_PODS_HEADER.split('|')

nheader = len(OSE_PODS_HEADER)


def stringifydate(row, k):
    if row[k]:
        row[k] = row[k].isoformat()


def y2k(row, k):
    dd = row[k]
    # print(dd, k)
    if dd:
        m, d, y = dd.split('/')
        row[k] = datetime.datetime(year=int(y), month=int(m), day=int(d))


def gen_rows(source_data):
    with open(source_data, 'r') as rfile:
        i = 0
        while 1:
            i += 1
            try:
                line = next(rfile)
            except UnicodeDecodeError:
                continue
            except StopIteration:
                break
            line = line.strip()
            line = line.split('|')[:-1]

            if len(line) != nheader:
                continue

            row = dict(zip(OSE_PODS_HEADER, line))
            if row['pod_basin'] in ('SP', 'SD', 'LWD'):
                continue
            if not row['easting'] or not row['northing'] or not row['utm_zone']:
                continue

            if row['finish_date'].strip():
                try:
                    # y2k(row, 'start_date')
                    y2k(row, 'finish_date')
                except ValueError as e:
                    print(row['start_date'], row['finish_date'])
                    raise e
                yield row


class TextLabel(staticmaps.Object):
    def __init__(self, latlng: s2sphere.LatLng, text: str) -> None:
        staticmaps.Object.__init__(self)
        self._latlng = latlng
        self._text = text
        self._margin = 4
        self._arrow = 16
        self._font_size = 12

    def latlng(self) -> s2sphere.LatLng:
        return self._latlng

    def bounds(self) -> s2sphere.LatLngRect:
        return s2sphere.LatLngRect.from_point(self._latlng)

    def extra_pixel_bounds(self) -> staticmaps.PixelBoundsT:
        # Guess text extents.
        tw = len(self._text) * self._font_size * 0.5
        th = self._font_size * 1.2
        w = max(self._arrow, tw + 2.0 * self._margin)
        return (int(w / 2.0), int(th + 2.0 * self._margin + self._arrow), int(w / 2), 0)

    def render_pillow(self, renderer: staticmaps.PillowRenderer) -> None:
        x, y = renderer.transformer().ll2pixel(self.latlng())
        x = x + renderer.offset_x()

        tw, th = renderer.draw().textsize(self._text)
        w = max(self._arrow, tw + 2 * self._margin)
        h = th + 2 * self._margin

        path = [
            (x, y),
            (x + self._arrow / 2, y - self._arrow),
            (x + w / 2, y - self._arrow),
            (x + w / 2, y - self._arrow - h),
            (x - w / 2, y - self._arrow - h),
            (x - w / 2, y - self._arrow),
            (x - self._arrow / 2, y - self._arrow),
        ]

        renderer.draw().polygon(path, fill=(255, 255, 255, 255))
        renderer.draw().line(path, fill=(255, 0, 0, 255))
        renderer.draw().text((x - tw / 2, y - self._arrow - h / 2 - th / 2), self._text, fill=(0, 0, 0, 255))


class MyMarker(staticmaps.Marker):
    def render_pillow(self, renderer: PillowRenderer) -> None:
        x, y = renderer.transformer().ll2pixel(self.latlng())
        x = x + renderer.offset_x()

        r = self.size()
        # dx = math.sin(math.pi / 3.0)
        # dy = math.cos(math.pi / 3.0)
        # cy = y - 2 * r
        ax, ay = x - r, y - r
        bx, by = x + r, y + r
        renderer.draw().chord((ax, ay, bx, by), 0, 360,
                              fill=self.color().int_rgba(),
                              width=2)


PROJECTIONS = {}


def get_latlon(w):
    zone = int(w['utm_zone'])
    if zone in PROJECTIONS:
        p = PROJECTIONS[zone]
    else:
        p = pyproj.Proj(proj='utm', zone=zone, ellps='WGS84')
        PROJECTIONS[zone] = p

    lon, lat = p(w['easting'], w['northing'], inverse=True)
    return lat, lon


def make_marker(w, color):
    lat, lon = get_latlon(w)
    pt = staticmaps.create_latlng(lat, lon)
    return MyMarker(pt, size=1, color=color)


def make_shapefile(wells):
    w = shapefile.Writer('wells.shp')
    w.field('name', 'C')
    for well in wells:
        lat, lon = get_latlon(well)
        w.point(lon, lat)
        w.record(f"{well['pod_basin']}{well['pod_nbr']}{well['pod_suffix']}")

    w.close()


def make_active_wells_visualization():
    tag, title, pod_status = 'active_wells', 'Active Wells', 'ACT'
    tag, title, pod_status = 'plugged_wells', 'Plugged Wells', 'PLG'
    tag, title, pod_status = 'notactive_wells', 'Non Active Wells', '!ACT'
    tag, title, pod_status = 'combined', '', ''
    combined = True

    source_path = './static/data/pod__04-01-2022.txt'
    # sortedwells = sorted(filter(func, gen_rows(source_path)), key=key)
    color = staticmaps.Color(0, 0, 0)
    context = make_context(zoom=11, center_lat=35, center_lon=-106.75)

    def func(r):
        """
        avaible status
        INC, PEN, CAP, ACT, PLG, CLW
        :param r:
        :return:
        """
        v = r['pod_status']
        if pod_status.startswith('!'):
            return v != pod_status
        else:
            return v == pod_status

    def nonactive(r):
        return r['pod_status'] != 'ACT'

    def active(r):
        return r['pod_status'] == 'ACT'

    # wells = list(gen_rows(source_path))
    # for s in set([r['pod_status'] for r in wells]):
    #     print(s)
    # for w in wells:
    if combined:
        rows = list(gen_rows(source_path))
        w = shapefile.Writer('wells.shp')
        w.field('name', 'C')
        w.field('status', 'C')
        color = staticmaps.Color(255, 0, 0)

        for well in filter(active, rows):
            m = make_marker(well, color=color)
            lat, lon = get_latlon(well)
            w.point(lon, lat)
            w.record(f"{well['pod_basin']}{well['pod_nbr']}{well['pod_suffix']}",
                     well['pod_status']
                     )
            context.add_object(m)

        color = staticmaps.Color(0, 0, 0)
        for well in filter(nonactive, rows):
            m = make_marker(well, color=color)
            lat, lon = get_latlon(well)
            w.point(lon, lat)
            w.record(f"{well['pod_basin']}{well['pod_nbr']}{well['pod_suffix']}",
                     well['pod_status']
                     )
            context.add_object(m)

    else:
        for w in filter(func, gen_rows(source_path)):
            pt = make_marker(w, color=color)
            context.add_object(pt)

    img = context.render_pillow(800, 800)
    draw = ImageDraw.Draw(img)
    fnt = ImageFont.truetype("Arial", 40)

    tw, th = draw.textsize(title, font=fnt)
    draw.text((400 - tw / 2, 50), title,
              fill='black',
              font=fnt)

    img.save('{}.png'.format(tag))


def make_context(center_lat=34.5, center_lon=-106, zoom=7):
    context = staticmaps.Context()
    context.set_zoom(zoom)
    context.set_center(staticmaps.create_latlng(center_lat, center_lon))
    context.set_tile_provider(staticmaps.tile_provider_OSM)
    return context


def make_gif_visualization():
    use_year = False
    use_cum_pods = True
    make_map = True
    use_decade_colors = 'winter'
    output_images = True
    source_path = './static/data/pod__04-01-2022.txt'

    def key(r):
        return r['finish_date']

    def key2(r):
        # print(r)
        d = r['finish_date']
        y = d.year
        if not use_year:
            y //= 10
        return y

    def func(r):
        d = r['finish_date']
        return 1900 <= d.year <= 2022

    projections = {}

    xs, ys = [], []

    imgs = []
    context = make_context()
    sortedwells = sorted(filter(func, gen_rows(source_path)), key=key)
    n = 0
    nsteps = 12
    if use_decade_colors:
        cmap = plt.get_cmap(use_decade_colors)
    logo = Image.open('Logos_sml.png')

    logo.thumbnail((sys.maxsize, 100), Resampling.LANCZOS)
    lw, lh = logo.size
    for i, (group, wells) in enumerate(groupby(sortedwells, key=key2)):
        wells = list(wells)
        print(group, len(wells))
        # if i>3:
        #     break

        if cmap:
            color = [int(ci * 255) for ci in cmap((i / nsteps))]
            color = staticmaps.Color(*color)

        n += len(wells)
        xs.append(group if use_year else group * 10)
        ys.append(n)
        if make_map:
            for w in wells:
                zone = int(w['utm_zone'])
                if zone in projections:
                    p = projections[zone]
                else:
                    p = pyproj.Proj(proj='utm', zone=zone, ellps='WGS84')
                    projections[zone] = p

                lon, lat = p(w['easting'], w['northing'], inverse=True)
                pt = staticmaps.create_latlng(lat, lon)
                kw = {}
                if use_decade_colors:
                    kw['color'] = color

                m = MyMarker(pt, size=1, **kw)
                context.add_object(m)

            img = context.render_pillow(800, 800)
            draw = ImageDraw.Draw(img)
            fnt = ImageFont.truetype("Arial", 32)

            decade = "1900-{}".format(group if use_year else (group * 10 + 9 if i < nsteps else 2022))
            txt = 'OSE Points of Diversion per decade ' + decade
            tw, th = draw.textsize(txt, font=fnt)
            draw.text((400 - tw / 2, 40), txt,
                      fill='black',
                      font=fnt)

            txt = "Number of points: {:>6n}".format(n)
            tw, th = draw.textsize(txt, font=fnt)
            draw.text((400 - tw / 2, 80), txt,
                      fill='black',
                      font=fnt)

            w, h = img.size
            img.paste(logo, (w - lw - 10, h - lh - 10), mask=logo)

            if output_images:
                if not os.path.isdir('output'):
                    os.mkdir('output')

                img.save('output/{}.png'.format(group))

            imgs.append(img)

    plt.plot(xs, ys)
    plt.xlabel('Year' if use_year else 'Decade')
    plt.ylabel('Cumulative Number of PODs')
    plt.tight_layout()
    plt.show()
    if imgs:
        img = imgs[0]
        duration = 750
        p = 'drill_{}_{}{}{}.gif'.format('year' if use_year else 'decade', duration,
                                         '_with_n' if use_cum_pods else '',
                                         '_{}'.format(use_decade_colors) if use_decade_colors else '')
        print(f'output to {p}')
        img.save(fp=p,
                 format='GIF',
                 append_images=imgs,
                 save_all=True, duration=duration, loop=0)


if __name__ == '__main__':
    make_gif_visualization()
    # make_active_wells_visualization()
# ============= EOF =============================================
