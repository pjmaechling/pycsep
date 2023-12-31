Catalogs
========

CSEP2 relaxes the assumption that forecasts supply Poissonian rates on structured and regular grids by allowing forecasts to
supply :ref:`stochastic event sets <stochastic-event-set>`. Classes will be defined for each catalog type and should extend the
:class:`AbstractBaseCatalog <csep.core.catalogs.AbstractBaseCatalog>` class.

.. autoclass:: csep.core.catalogs.AbstractBaseCatalog
  :members:

.. autoclass:: csep.core.catalogs.ZMAPCatalog
  :members:

.. autoclass:: csep.core.catalogs.UCERF3Catalog
  :members:

.. autoclass:: csep.core.catalogs.ComcatCatalog
  :members:
