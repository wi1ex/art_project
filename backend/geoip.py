"""Country lookup uses a local mmap database; visitors' IPs stay on our server."""
import ipaddress
import logging

import maxminddb


class CountryLookup:
    def __init__(self, path):
        self.reader = None
        try:
            self.reader = maxminddb.open_database(path)
        except (OSError, ValueError, maxminddb.InvalidDatabaseError):
            logging.getLogger('leads').warning('Country database unavailable; automatic language defaults to English')

    def __call__(self, ip):
        try:
            address = ipaddress.ip_address(ip)
            if not address.is_global or not self.reader:
                return None
            record = self.reader.get(str(address))
            country = record.get('country') if isinstance(record, dict) else None
            code = country.get('iso_code') if isinstance(country, dict) else None
            return code if isinstance(code, str) else None
        except (OSError, ValueError, maxminddb.InvalidDatabaseError):
            return None

    def close(self):
        if self.reader:
            self.reader.close()
