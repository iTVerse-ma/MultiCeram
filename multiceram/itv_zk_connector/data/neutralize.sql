-- itv_zk_connector : une copie de base ne doit jamais écrire dans BioTime ni interroger la production.
UPDATE itv_zk_backend
   SET read_only = true,
       active = false,
       token = NULL;
