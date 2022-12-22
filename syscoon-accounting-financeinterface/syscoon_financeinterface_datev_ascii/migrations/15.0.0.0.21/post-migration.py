def migrate(cr, version):
    import logging
    import uuid

    _logger = logging.getLogger(__name__)
    _logger.info('post_init: Start migration of BEDI Beleglink')

    cr.execute("SELECT id FROM account_move WHERE datev_bedi != ''")
    ids = cr.fetchall()

    for id in ids:
        uuid4_str = str(uuid.uuid4())
        cr.execute("UPDATE account_move set datev_bedi = %s where id = %s", (uuid4_str, id[0]))
        _logger.info('post_init: Setting datev_bedi = %s to id = %s' % (uuid4_str, id[0]))

    _logger.info('post_init: End migration of BEDI Beleglink')

