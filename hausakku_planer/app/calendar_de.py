"""German public holidays as price day types. stdlib only.

Exchange prices on a national holiday look like a Sunday (little industry), on
Christmas Eve, New Year's Eve and the regional holidays Corpus Christi / All Saints
like a Saturday. Backtest Sep 2024-Nov 2026: hourly price error on holidays and the
day after 4.18 -> 3.99 ct, 20.12.-03.01. 3.67 -> 3.25 ct, elsewhere unchanged.
"""
from datetime import date,timedelta


def easter(year):
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a=year%19;b=year//100;c=year%100;d=b//4;e=b%4;f=(b+8)//25;g=(b-f+1)//3
    h=(19*a+b-d-g+15)%30;i=c//4;k=c%4;l=(32+2*e+2*i-h-k)%7;m=(a+11*h+22*l)//451
    return date(year,(h+l-7*m+114)//31,(h+l-7*m+114)%31+1)


_cache={}
def holidays(year):
    """{date: weekday it behaves like (5 Saturday, 6 Sunday)}."""
    if year not in _cache:
        e=easter(year)
        _cache[year]={date(year,1,1):6,e-timedelta(days=2):6,e+timedelta(days=1):6,date(year,5,1):6,
                      e+timedelta(days=39):6,e+timedelta(days=50):6,date(year,10,3):6,date(year,12,25):6,date(year,12,26):6,
                      date(year,12,24):5,date(year,12,31):5,e+timedelta(days=60):5,date(year,11,1):5}
    return _cache[year]


def day_type(day,use_holidays=True):
    """Weekday index 0..6 for price statistics; a holiday counts as the weekday it resembles."""
    return holidays(day.year).get(day,day.weekday()) if use_holidays else day.weekday()
