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

import folium
import json
from itertools import groupby
import pyproj
import pandas
import s2sphere
import staticmaps
from PIL import ImageDraw, ImageFont
from mpl_toolkits.basemap import Basemap
import matplotlib.pyplot as plt
from staticmaps import PillowRenderer

OSE_PODS_HEADER = 'pod_basin|pod_nbr|pod_suffix|ref|pod_name|tws|rng|sec|qtr_4th|qtr_16th|qtr_64th|qtr_256th|qtr_1024th|qtr_4096|blk|zone|x|y|grant|legal|county|license_nbr|driller|start_date|finish_date|plug_date|pcw_rcv_date|elevation|depth_well|grnd_wtr_src|percent_shallow|depth_water|log_file_date|sched_date|usgs_map_code|usgs_map_suffix|usgs_map_quad1|usgs_map_quad2|use_of_well|pump_type|pump_serial|discharge|photo|photo_date|photo_punch|aquifer|sys_date|measure|subdiv_name|subdiv_location|municipality|municipality_loc|restrict|usgs_pod_nbr|lat_deg|lat_min|lat_sec|lon_deg|lon_min|lon_sec|surface_code|estimate_yield|pod_status|casing_size|ditch_name|utm_zone|easting|northing|datum|utm_source|utm_accuracy|xy_source|xy_accuracy|lat_lon_source|lat_lon_accuracy|tract_nbr|map_nbr|surv_map|other_loc|pod_rec_nbr|cfs_start_mday|cfs_end_mday|cfs_cnv_factor|cs_code|wrats_s_id|utm_error|pod_sub_basin|well_tag|static_level'
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
        # m, d, y = int(m), int(d), int(y)
        # if y <= 22:
        #     y = 2000 + y
        #         # elif y < 100:
        #         #     y = 1900 + y
        #         if int(y)>2022:
        #             print(dd)
        row[k] = datetime.datetime(year=int(y), month=int(m), day=int(d))


def gen_rows():
    p = './static/data/pod__04-01-2022.txt'
    with open(p, 'r') as rfile:
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
            if row['pod_basin'] in ('SP', 'SD'):
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


def make_gif_visualization():
    use_year = False
    use_cum_pods = True
    make_map = True
    use_decade_colors = 'magma'

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
    context = staticmaps.Context()
    context.set_zoom(7)
    center_lat = 34.5
    center_lon = -106
    context.set_center(staticmaps.create_latlng(center_lat, center_lon))
    context.set_tile_provider(staticmaps.tile_provider_OSM)
    imgs = []
    sortedwells = sorted(filter(func, gen_rows()), key=key)
    n = 0
    nsteps = 12
    if use_decade_colors:
        cmap = plt.get_cmap(use_decade_colors)

    for i, (group, wells) in enumerate(groupby(sortedwells, key=key2)):
        wells = list(wells)
        print(group, len(wells))
        # if i%3:
        #     continue
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
                    # kw['color'] = staticmaps.Color((200-i*20)%255, (200+i*20)%255, (200-i*20)%255)
                    kw['color'] = color

                m = MyMarker(pt, size=1, **kw)
                context.add_object(m)

            img = context.render_pillow(800, 800)
            draw = ImageDraw.Draw(img)
            fnt = ImageFont.truetype("Arial", 40)
            txt = "{}".format(group if use_year else group * 10)
            if use_cum_pods:
                txt += ' Cumulative PODs:{:>6s}'.format(str(n))

            tw, th = draw.textsize(txt, font=fnt)
            draw.text((400 - tw / 2, 50), txt,
                      fill='black',
                      font=fnt)
            imgs.append(img)

    plt.plot(xs, ys)
    plt.xlabel('Year' if use_year else 'Decade')
    plt.ylabel('Cumulative Number of PODs')
    plt.tight_layout()
    plt.show()
    if imgs:
        img = imgs[0]
        duration = 500
        img.save(fp='drill_{}_{}{}{}.gif'.format('year' if use_year else 'decade', duration,
                                                 '_with_n' if use_cum_pods else '',
                                                 '_{}'.format(use_decade_colors) if use_decade_colors else ''),
                 format='GIF',
                 append_images=imgs,
                 save_all=True, duration=duration, loop=0)


if __name__ == '__main__':
    make_gif_visualization()
# ============= EOF =============================================
