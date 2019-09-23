var $ = require('jquery');
var domready = require('domready');

require('bootstrap');
var Highcharts = require('Highcharts');
require('Highcharts-export')(Highcharts);
require('Highcharts-more')(Highcharts);
var chroma = require('chroma-js');
var _ = require('underscore');

domready(function() {
  if (typeof bubble_data_url !== 'undefined') {
    var highchartsOptions = {
      chart: {
        type: 'bubble',
        plotBorderWidth: 1,
        zoomType: 'xy',
      },

      legend: {
        enabled: false,
      },

      title: {
        text: 'Price-per-unit cost of <br>' + generic_name,
      },
      subtitle: {
        text: null,
      },
      yAxis: {
        type: 'category',
        gridLineWidth: 1,
        title: {
          text: null,
        },
        labels: {
          style: {
            textOverflow: 'clip',
          },
          formatter: function() {
            var label = this.value.name || '';
            if (this.value.is_generic) {
              label += ' <span style="color: red">';
              label += '(prescribed generically)</span>';
            }
            return label;
          }
        },
      },

      xAxis: {
        gridLineWidth: 1,
        title: {
          text: 'PPU',
        },
        labels: {
          formatter: function() {
            if (this.value < 0) {
              return '';
            } else {
              return '£' + this.value;
            }
          }
        },
        plotLines: [{
          color: 'black',
          dashStyle: 'dot',
          width: 2,
          value: 12,
          label: {
            y: 15,
            style: {
              fontStyle: 'italic',
            },
            text: 'Mean PPU for ' + highlight_name,
          },
          zIndex: 3,
        }],
      },
      tooltip: {
        useHTML: true,
        headerFormat: '',
        pointFormat: '{point.z:,.0f} units of {point.name} @ £{point.x:,.2f}',
        followPointer: true,
      },

      series: [{
        data: [
        ],
      }],

    };
    /** Sets color on each presentation on a green-red scale according
     * to its mean PPU */
    function setGenericColours(data) {
      var scale = chroma.scale(['green', 'yellow', 'red']);
      var means = _.map(data.series, function(d) {
        return d.mean_ppu;
      });
      var maxPPU = _.max(means);
      var minPPU = _.min(means);
      var maxRange = maxPPU - minPPU;
      _.each(data.series, function(d) {
        var ratio = (d.mean_ppu - minPPU) / maxRange;
        d.color = scale(ratio).hex();
      });
    }
    function renderChart(url, elementSelector, orgName) {
      $.getJSON(
        url,
        function(data) {
          setGenericColours(data);
          _.each(data.series, function(d) {
            var tmp = d.x;
            d.x = d.y;
            // Translate from 1-index to 0-index
            d.y = tmp - 1;
          });

          // By default, the size (radius) of largest bubble is 20% the height
          // of the chart, and the smallest is 8 pixels.  The sizes of the
          // other bubbles are determined so that they fall between these two
          // sizes appropriately.  This is usually fine, when some of our
          // bubbles are for many prescriptions (big bubbles) and some are for
          // fewer (small bubbles).  But it breaks down when all bubbles are
          // for a similar number of prescriptions, when we need all bubbles to
          // be a similar size.  We want the size of the smallest bubble to be
          // in proportion to the size of the largest.
          var sizes = data.series.map(function(d) {return d['z']});
          var ratio = Math.min.apply(null, sizes) / Math.max.apply(null, sizes);
          var maxSize = '20%';
          var minSize = (20 * ratio) + '%';

          var options = $.extend(true, {}, highchartsOptions);
          options.chart.width = $('.tab-content').width();
          options.chart.height = Math.max(400, data.categories.length * 20 + 200);
          options.subtitle.text = 'for prescriptions within ' + orgName;
          options.series[0].data = data.series;
          options.xAxis.plotLines[0].value = data.plotline;
          options.yAxis.categories = data.categories;
          options.plotOptions = {
            bubble: {
              minSize: minSize,
              maxSize: maxSize,
            }
          };
          $(elementSelector).highcharts(options);
        }
      );
    }
    renderChart(bubble_data_url, '#all_practices_chart', 'NHS England');
    renderChart(bubble_data_url+'&focus=1', '#highlight_chart', highlight_name);
  }
});
