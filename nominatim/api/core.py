# SPDX-License-Identifier: GPL-2.0-only
#
# This file is part of Nominatim. (https://nominatim.org)
#
# Copyright (C) 2023 by the Nominatim developer community.
# For a full list of authors see the git log.
"""
Implementation of classes for API access via libraries.
"""
from typing import Mapping, Optional, Any, AsyncIterator, Dict
import asyncio
import contextlib
from pathlib import Path

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as sa_asyncio
import asyncpg

from nominatim.db.sqlalchemy_schema import SearchTables
from nominatim.config import Configuration
from nominatim.api.connection import SearchConnection
from nominatim.api.status import get_status, StatusResult
from nominatim.api.lookup import get_place_by_id
from nominatim.api.reverse import reverse_lookup
from nominatim.api.types import PlaceRef, LookupDetails, AnyPoint, DataLayer
from nominatim.api.results import DetailedResult, ReverseResult


class NominatimAPIAsync:
    """ API loader asynchornous version.
    """
    def __init__(self, project_dir: Path,
                 environ: Optional[Mapping[str, str]] = None) -> None:
        self.config = Configuration(project_dir, environ)
        self.server_version = 0

        self._engine_lock = asyncio.Lock()
        self._engine: Optional[sa_asyncio.AsyncEngine] = None
        self._tables: Optional[SearchTables] = None
        self._property_cache: Dict[str, Any] = {'DB:server_version': 0}


    async def setup_database(self) -> None:
        """ Set up the engine and connection parameters.

            This function will be implicitly called when the database is
            accessed for the first time. You may also call it explicitly to
            avoid that the first call is delayed by the setup.
        """
        async with self._engine_lock:
            if self._engine:
                return

            dsn = self.config.get_database_params()

            dburl = sa.engine.URL.create(
                       'postgresql+asyncpg',
                       database=dsn.get('dbname'),
                       username=dsn.get('user'), password=dsn.get('password'),
                       host=dsn.get('host'), port=int(dsn['port']) if 'port' in dsn else None,
                       query={k: v for k, v in dsn.items()
                              if k not in ('user', 'password', 'dbname', 'host', 'port')})
            engine = sa_asyncio.create_async_engine(
                             dburl, future=True,
                             connect_args={'server_settings': {
                                'DateStyle': 'sql,european',
                                'max_parallel_workers_per_gather': '0'
                             }})

            try:
                async with engine.begin() as conn:
                    result = await conn.scalar(sa.text('SHOW server_version_num'))
                    server_version = int(result)
            except asyncpg.PostgresError:
                server_version = 0

            if server_version >= 110000:
                @sa.event.listens_for(engine.sync_engine, "connect")
                def _on_connect(dbapi_con: Any, _: Any) -> None:
                    cursor = dbapi_con.cursor()
                    cursor.execute("SET jit_above_cost TO '-1'")
                # Make sure that all connections get the new settings
                await self.close()

            self._property_cache['DB:server_version'] = server_version

            self._tables = SearchTables(sa.MetaData(), engine.name) # pylint: disable=no-member
            self._engine = engine


    async def close(self) -> None:
        """ Close all active connections to the database. The NominatimAPIAsync
            object remains usable after closing. If a new API functions is
            called, new connections are created.
        """
        if self._engine is not None:
            await self._engine.dispose()


    @contextlib.asynccontextmanager
    async def begin(self) -> AsyncIterator[SearchConnection]:
        """ Create a new connection with automatic transaction handling.

            This function may be used to get low-level access to the database.
            Refer to the documentation of SQLAlchemy for details how to use
            the connection object.
        """
        if self._engine is None:
            await self.setup_database()

        assert self._engine is not None
        assert self._tables is not None

        async with self._engine.begin() as conn:
            yield SearchConnection(conn, self._tables, self._property_cache)


    async def status(self) -> StatusResult:
        """ Return the status of the database.
        """
        try:
            async with self.begin() as conn:
                status = await get_status(conn)
        except asyncpg.PostgresError:
            return StatusResult(700, 'Database connection failed')

        return status


    async def lookup(self, place: PlaceRef,
                     details: Optional[LookupDetails] = None) -> Optional[DetailedResult]:
        """ Get detailed information about a place in the database.

            Returns None if there is no entry under the given ID.
        """
        async with self.begin() as conn:
            return await get_place_by_id(conn, place, details or LookupDetails())


    async def reverse(self, coord: AnyPoint, max_rank: Optional[int] = None,
                      layer: Optional[DataLayer] = None,
                      details: Optional[LookupDetails] = None) -> Optional[ReverseResult]:
        """ Find a place by its coordinates. Also known as reverse geocoding.

            Returns the closest result that can be found or None if
            no place matches the given criteria.
        """
        # The following negation handles NaN correctly. Don't change.
        if not abs(coord[0]) <= 180 or not abs(coord[1]) <= 90:
            # There are no results to be expected outside valid coordinates.
            return None

        if layer is None:
            layer = DataLayer.ADDRESS | DataLayer.POI

        max_rank = max(0, min(max_rank or 30, 30))

        async with self.begin() as conn:
            return await reverse_lookup(conn, coord, max_rank, layer,
                                        details or LookupDetails())


class NominatimAPI:
    """ API loader, synchronous version.
    """

    def __init__(self, project_dir: Path,
                 environ: Optional[Mapping[str, str]] = None) -> None:
        self._loop = asyncio.new_event_loop()
        self._async_api = NominatimAPIAsync(project_dir, environ)


    def close(self) -> None:
        """ Close all active connections to the database. The NominatimAPIAsync
            object remains usable after closing. If a new API functions is
            called, new connections are created.
        """
        self._loop.run_until_complete(self._async_api.close())
        self._loop.close()


    @property
    def config(self) -> Configuration:
        """ Return the configuration used by the API.
        """
        return self._async_api.config

    def status(self) -> StatusResult:
        """ Return the status of the database.
        """
        return self._loop.run_until_complete(self._async_api.status())


    def lookup(self, place: PlaceRef,
               details: Optional[LookupDetails] = None) -> Optional[DetailedResult]:
        """ Get detailed information about a place in the database.
        """
        return self._loop.run_until_complete(self._async_api.lookup(place, details))


    def reverse(self, coord: AnyPoint, max_rank: Optional[int] = None,
                layer: Optional[DataLayer] = None,
                details: Optional[LookupDetails] = None) -> Optional[ReverseResult]:
        """ Find a place by its coordinates. Also known as reverse geocoding.

            Returns the closest result that can be found or None if
            no place matches the given criteria.
        """
        return self._loop.run_until_complete(
                   self._async_api.reverse(coord, max_rank, layer, details))
