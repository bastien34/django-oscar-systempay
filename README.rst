How to use
==========

This is fork of `django-oscar-systempay`, a payment solution intended to be used
with django-oscar.

The current implementation is based on the document V2 available online.

`SystemPay documentation <https://systempay.cyberpluspaiement.com/html/documentation.html>`_

Install
-------
Install from the github repository.

    ``pip install git+https://github.com/bastien34/django-oscar-systempay.git``

Config
------

To integrate systempay to your oscar project, you need to overwrite the root app
in order to include the bench of urls used for systempay.

`Override the root app <http://django-oscar.readthedocs.io/en/releases-1.3/howto/how_to_change_a_url.html?highlight=urls#changing-the-root-app>`_


**Settings `INSTALLED_APPS` and `context_processors`**

Start by adding `systempay` to your `INSTALLED_APPS` settings:

.. code:: python

        INSTALLED_APPS = (
            ...,
            'systempay',
        )

Systempay need a context processor to load the bank URL page as well. So in
`TEMPLATES` add the systempay context processor:

.. code:: python

    'systempay.context_processors.gateway'

For testing purpose, you might need to add `LOCAL_SERVER` to your local settings.

.. code:: python

    # config/settings/local.py
    LOCALE_SERVER = True

**Create an app file in your project as following:**


.. code:: python

    # myproject/app.py
    from oscar.app import Shop as CoreShop
    from oscar.core.loading import get_class


    class Shop(CoreShop):

        systempay_app = get_class('systempay.app', 'application')

        def get_urls(self):
            urls = super().get_urls()

            urls += [
                url(r'^systempay/', include(self.systempay_app.urls)),
            ]
            return urls

    application = Shop()


**Link your root urls file to the new application**

.. code:: python

    # config/urls.py
    (...)
    from materielfroid.app import application


    urlpatterns = [
        ...
        url(r'', include(application.urls)),
        ]

**Configure `site`**

`Django-oscar-systempay` uses Site to build its urls. So you must configure
it correctly before testing.

.. code:: python

    from django.contrib.sites.models import Site
    # we suppose you only have one site here
    site = Site.objects.first()
    site.domain = "your.domain.com"
    site.save()



Requirements
------------

`Django-oscar-systempay` is compatible with Python 3 and Django 1.9. No test
has been done on Python 2.7 for now.


